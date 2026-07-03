// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"math/rand"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Agent runs the poll → validate → apply → report convergence loop.
type Agent struct {
	cfg    Config
	client *Client
	vector *Vector

	etag           string // last seen config ETag (If-None-Match)
	appliedGen     int    // generation currently applied to disk
	healthy        bool   // is Vector running the applied config
	vectorVersion  string // installed Vector semver (reported in status)
	desiredVersion string // fleet-wide desired version from the control plane
}

func NewAgent(cfg Config, client *Client, vector *Vector) *Agent {
	return &Agent{cfg: cfg, client: client, vector: vector, healthy: true}
}

const maxBackoff = 5 * time.Minute

// Run loops until the context is cancelled. Network/server errors trigger
// exponential backoff with jitter; a successful cycle resets to the base
// interval.
func (a *Agent) Run(ctx context.Context) {
	a.vectorVersion = a.vector.Version(ctx)
	log.Printf("agent started: instance=%s server=%s interval=%s vector=%q",
		a.cfg.InstanceID, a.cfg.ServerURL, a.cfg.PollInterval, a.vectorVersion)

	backoff := a.cfg.PollInterval
	for {
		if err := a.cycle(ctx); err != nil {
			if ctx.Err() != nil {
				return
			}
			backoff = nextBackoff(backoff)
			log.Printf("cycle error: %v (retrying in %s)", err, backoff.Round(time.Second))
		} else {
			backoff = a.cfg.PollInterval
		}

		select {
		case <-ctx.Done():
			log.Printf("shutting down")
			return
		case <-time.After(backoff):
		}
	}
}

// cycle runs one poll/apply/report. It returns an error only for conditions
// that should trigger backoff (couldn't reach the server). Config-level
// problems (validate/reload failures) are reported as status, not returned.
func (a *Agent) cycle(ctx context.Context) error {
	res, err := a.client.FetchConfig(ctx, a.etag)
	if err != nil {
		return err
	}

	if res.NotModified {
		a.reconcileVersion(ctx) // retry an unconverged version even when config is unchanged
		a.report(ctx, "ok", "")
		return nil
	}

	for _, w := range res.Warnings {
		log.Printf("config warning (gen %d): %s", res.Generation, w)
	}

	// Bring Vector to the desired version BEFORE validating/applying config, so
	// the right binary validates it.
	a.desiredVersion = res.VectorVersion
	a.reconcileVersion(ctx)

	// Write TLS cert material before the config that references it, so validate
	// and reload see the files at the paths the config points to. Unlike a
	// validate rejection (deterministic — caching the ETag avoids re-fetching a
	// known-bad config), a write failure is usually transient (disk/permission),
	// so DON'T cache the ETag: return an error to back off and retry next tick.
	if err := writeConfigFiles(res.Files, a.cfg.CertsDir); err != nil {
		a.healthy = false
		a.report(ctx, "reload_failed", err.Error())
		return fmt.Errorf("write cert files (gen %d): %w", res.Generation, err)
	}

	if err := a.vector.Apply(ctx, res.ConfigYAML); err != nil {
		var ve *ValidateError
		if errors.As(err, &ve) {
			// Running config is untouched. Stop re-fetching this bad config every
			// tick (its ETag won't change until the operator fixes it).
			a.etag = res.ETag
			log.Printf("generation %d rejected by validate; keeping current config", res.Generation)
			a.report(ctx, "validate_failed", ve.Error())
			return nil
		}
		// Swap succeeded but reload failed: config is on disk, Vector may not be
		// running it. Record it as applied-but-unhealthy and move on.
		a.etag = res.ETag
		a.appliedGen = res.Generation
		a.healthy = false
		log.Printf("generation %d applied but reload failed: %v", res.Generation, err)
		a.report(ctx, "reload_failed", err.Error())
		return nil
	}

	a.etag = res.ETag
	a.appliedGen = res.Generation
	a.healthy = true
	log.Printf("applied generation %d", res.Generation)
	a.report(ctx, "ok", "")
	return nil
}

// reconcileVersion brings Vector to the fleet's desired version. If an install
// command is configured it updates (then reloads); otherwise it just logs the
// drift. No-op when no version is desired or it already matches.
func (a *Agent) reconcileVersion(ctx context.Context) {
	want := a.desiredVersion
	if want == "" || want == a.vectorVersion {
		return
	}
	if !a.vector.HasInstaller() {
		log.Printf("vector version drift: installed=%q desired=%q (set VECTOR_INSTALL_CMD to auto-update)",
			a.vectorVersion, want)
		return
	}
	log.Printf("updating vector %q -> %q", a.vectorVersion, want)
	if err := a.vector.Install(ctx, want); err != nil {
		log.Printf("vector update failed: %v", err)
		return
	}
	if err := a.vector.reload(ctx); err != nil {
		log.Printf("vector restart after update failed: %v", err)
	}
	a.vectorVersion = a.vector.Version(ctx)
	log.Printf("vector now %q", a.vectorVersion)
}

func (a *Agent) report(ctx context.Context, state, lastErr string) {
	err := a.client.ReportStatus(ctx, Status{
		AppliedGeneration: a.appliedGen,
		VectorHealthy:     a.healthy,
		State:             state,
		LastError:         lastErr,
		VectorVersion:     a.vectorVersion,
	})
	if err != nil && ctx.Err() == nil {
		log.Printf("status report failed: %v", err)
	}
}

func nextBackoff(cur time.Duration) time.Duration {
	next := cur * 2
	if next > maxBackoff {
		next = maxBackoff
	}
	// Full jitter in [next/2, next] to avoid thundering herds across a fleet.
	jitter := next/2 + time.Duration(rand.Int63n(int64(next/2)+1))
	return jitter
}

// writeConfigFiles writes TLS cert material to the host before the config that
// references it. Atomic write-then-rename; keys 0600, certs 0644; dirs 0700.
//
// The agent runs as root and the paths come from the control plane, so every
// write is confined to certsDir (the managed component-certs tree). A path
// outside it — or one using ".." to escape it — is rejected, so a compromised
// or malicious server cannot turn the deploy pull into an arbitrary root file
// write (e.g. /root/.ssh/authorized_keys, /etc/cron.d/...).
func writeConfigFiles(files []ConfigFile, certsDir string) error {
	base := filepath.Clean(certsDir)
	for _, f := range files {
		if !filepath.IsAbs(f.Path) {
			return fmt.Errorf("cert file path must be absolute: %s", f.Path)
		}
		clean := filepath.Clean(f.Path)
		if clean != base && !strings.HasPrefix(clean, base+string(os.PathSeparator)) {
			return fmt.Errorf(
				"refusing to write %s: outside managed cert dir %s", f.Path, base,
			)
		}
		if err := os.MkdirAll(filepath.Dir(clean), 0o700); err != nil {
			return fmt.Errorf("mkdir for %s: %w", f.Path, err)
		}
		mode := os.FileMode(f.Mode)
		if mode == 0 {
			mode = 0o644
		}
		tmp := clean + ".tmp"
		if err := os.WriteFile(tmp, []byte(f.Content), mode); err != nil {
			return fmt.Errorf("write %s: %w", clean, err)
		}
		// WriteFile applies umask; enforce the intended mode (0600 for keys).
		if err := os.Chmod(tmp, mode); err != nil {
			os.Remove(tmp)
			return fmt.Errorf("chmod %s: %w", clean, err)
		}
		if err := os.Rename(tmp, clean); err != nil {
			os.Remove(tmp)
			return fmt.Errorf("rename %s: %w", clean, err)
		}
	}
	return nil
}
