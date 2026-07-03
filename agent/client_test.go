// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package main

import (
	"os"
	"path/filepath"
	"testing"
)

// A configured-but-unusable AGENT_CA_CERT must fail fast, not silently fall back
// to the system trust store (ops #6).
func TestNewClientFailsOnUnusableCA(t *testing.T) {
	base := Config{ServerURL: "https://x", InstanceID: "i", Token: "t"}

	t.Run("missing CA file", func(t *testing.T) {
		cfg := base
		cfg.CACertPath = filepath.Join(t.TempDir(), "does-not-exist.pem")
		if _, err := NewClient(cfg); err == nil {
			t.Fatal("expected error for unreadable CA path")
		}
	})

	t.Run("unparseable CA file", func(t *testing.T) {
		p := filepath.Join(t.TempDir(), "junk.pem")
		if err := os.WriteFile(p, []byte("not a pem"), 0o600); err != nil {
			t.Fatal(err)
		}
		cfg := base
		cfg.CACertPath = p
		if _, err := NewClient(cfg); err == nil {
			t.Fatal("expected error for unparseable CA file")
		}
	})

	t.Run("no CA configured succeeds", func(t *testing.T) {
		if _, err := NewClient(base); err != nil {
			t.Fatalf("expected success with system roots, got %v", err)
		}
	})

	t.Run("insecure flag succeeds (with warning)", func(t *testing.T) {
		cfg := base
		cfg.InsecureTLS = true
		if _, err := NewClient(cfg); err != nil {
			t.Fatalf("expected success, got %v", err)
		}
	})
}
