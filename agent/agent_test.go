// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package main

import (
	"os"
	"path/filepath"
	"testing"
)

// The agent runs as root and file paths come from the control plane, so
// writeConfigFiles must confine every write to the managed cert dir. A path
// outside it — or one escaping via ".." — must be refused, not written.
func TestWriteConfigFilesConfinesToCertsDir(t *testing.T) {
	base := t.TempDir()

	t.Run("writes a file inside the managed dir", func(t *testing.T) {
		p := filepath.Join(base, "abc123", "crt.pem")
		if err := writeConfigFiles([]ConfigFile{{Path: p, Content: "PEM", Mode: 0o600}}, base); err != nil {
			t.Fatalf("expected success, got %v", err)
		}
		got, err := os.ReadFile(p)
		if err != nil {
			t.Fatalf("read back: %v", err)
		}
		if string(got) != "PEM" {
			t.Fatalf("content = %q, want %q", got, "PEM")
		}
		fi, _ := os.Stat(p)
		if fi.Mode().Perm() != 0o600 {
			t.Fatalf("mode = %v, want 0600", fi.Mode().Perm())
		}
	})

	t.Run("rejects a path escaping via ..", func(t *testing.T) {
		evil := filepath.Join(base, "..", "..", "root", ".ssh", "authorized_keys")
		if err := writeConfigFiles([]ConfigFile{{Path: evil, Content: "x", Mode: 0o600}}, base); err == nil {
			t.Fatalf("expected refusal for %s", evil)
		}
		if _, err := os.Stat(evil); err == nil {
			t.Fatalf("traversal path was written: %s", evil)
		}
	})

	t.Run("rejects an absolute path outside the managed dir", func(t *testing.T) {
		if err := writeConfigFiles([]ConfigFile{{Path: "/etc/cron.d/evil", Content: "x", Mode: 0o644}}, base); err == nil {
			t.Fatal("expected refusal for /etc/cron.d/evil")
		}
	})

	t.Run("rejects a relative path", func(t *testing.T) {
		if err := writeConfigFiles([]ConfigFile{{Path: "relative/crt.pem", Content: "x", Mode: 0o644}}, base); err == nil {
			t.Fatal("expected refusal for a relative path")
		}
	})

	t.Run("rejects a sibling dir sharing the base prefix", func(t *testing.T) {
		// /tmp/base-evil must not pass a prefix check against /tmp/base.
		sibling := base + "-evil/crt.pem"
		if err := writeConfigFiles([]ConfigFile{{Path: sibling, Content: "x", Mode: 0o644}}, base); err == nil {
			t.Fatalf("expected refusal for sibling %s", sibling)
		}
	})
}
