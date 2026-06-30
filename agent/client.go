// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"time"
)

// Client talks to the VortexFlow agent control plane.
type Client struct {
	baseURL    string
	instanceID string
	token      string
	http       *http.Client
}

// NewClient builds a control-plane client. InsecureTLS disables certificate
// verification (dev only).
func NewClient(cfg Config) *Client {
	transport := &http.Transport{}
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12}
	if cfg.InsecureTLS {
		tlsCfg.InsecureSkipVerify = true //nolint:gosec // opt-in dev flag
	} else if cfg.CACertPath != "" {
		// Trust the leader's (self-signed) CA without disabling verification.
		if pem, err := os.ReadFile(cfg.CACertPath); err == nil {
			pool := x509.NewCertPool()
			if pool.AppendCertsFromPEM(pem) {
				tlsCfg.RootCAs = pool
			} else {
				log.Printf("warning: no certs parsed from AGENT_CA_CERT %s", cfg.CACertPath)
			}
		} else {
			log.Printf("warning: cannot read AGENT_CA_CERT %s: %v", cfg.CACertPath, err)
		}
	}
	transport.TLSClientConfig = tlsCfg
	return &Client{
		baseURL:    cfg.ServerURL,
		instanceID: cfg.InstanceID,
		token:      cfg.Token,
		http:       &http.Client{Timeout: 30 * time.Second, Transport: transport},
	}
}

// ConfigResult is the outcome of a config poll.
// ConfigFile is a file (TLS cert/key/ca) the agent must write on the host before
// validate+reload; the config's tls.*_file paths point at these.
type ConfigFile struct {
	Path    string `json:"path"`
	Content string `json:"content"`
	Mode    int    `json:"mode"`
}

type ConfigResult struct {
	NotModified   bool   // server returned 304 — nothing changed
	Generation    int    `json:"generation"`
	ConfigYAML    string `json:"config_yaml"`
	VectorVersion string `json:"vector_version"` // desired version ("" = unmanaged)
	Warnings      []string
	Files         []ConfigFile // cert material to write before applying
	ETag          string       // opaque; pass back via If-None-Match next poll
}

// FetchConfig polls GET /agent/{id}/config. prevETag is sent as If-None-Match;
// a 304 yields ConfigResult{NotModified: true}.
func (c *Client) FetchConfig(ctx context.Context, prevETag string) (ConfigResult, error) {
	url := fmt.Sprintf("%s/api/v1/agent/%s/config", c.baseURL, c.instanceID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return ConfigResult{}, err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if prevETag != "" {
		req.Header.Set("If-None-Match", prevETag)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return ConfigResult{}, err
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusNotModified:
		return ConfigResult{NotModified: true, ETag: prevETag}, nil
	case http.StatusOK:
		var body struct {
			Generation    int          `json:"generation"`
			ConfigYAML    string       `json:"config_yaml"`
			VectorVersion string       `json:"vector_version"`
			Warnings      []string     `json:"warnings"`
			Files         []ConfigFile `json:"files"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
			return ConfigResult{}, fmt.Errorf("decode config: %w", err)
		}
		return ConfigResult{
			Generation:    body.Generation,
			ConfigYAML:    body.ConfigYAML,
			VectorVersion: body.VectorVersion,
			Warnings:      body.Warnings,
			Files:         body.Files,
			ETag:          resp.Header.Get("ETag"),
		}, nil
	default:
		return ConfigResult{}, fmt.Errorf("config poll: unexpected status %d: %s",
			resp.StatusCode, readSnippet(resp.Body))
	}
}

// Status is the agent's self-reported state.
type Status struct {
	AppliedGeneration int    `json:"applied_generation"`
	VectorHealthy     bool   `json:"vector_healthy"`
	State             string `json:"status"`
	LastError         string `json:"last_error,omitempty"`
	VectorVersion     string `json:"vector_version,omitempty"`
}

// ReportStatus posts the agent's state to POST /agent/{id}/status.
func (c *Client) ReportStatus(ctx context.Context, s Status) error {
	url := fmt.Sprintf("%s/api/v1/agent/%s/status", c.baseURL, c.instanceID)
	payload, err := json.Marshal(s)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("status report: unexpected status %d: %s",
			resp.StatusCode, readSnippet(resp.Body))
	}
	return nil
}

func readSnippet(r io.Reader) string {
	b, _ := io.ReadAll(io.LimitReader(r, 512))
	return string(b)
}
