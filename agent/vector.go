// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

// Vector wraps the local Vector binary and managed config file.
type Vector struct {
	bin        string
	configPath string
	reloadCmd  []string
	installCmd []string
}

func NewVector(cfg Config) *Vector {
	return &Vector{
		bin:        cfg.VectorBin,
		configPath: cfg.ConfigPath,
		reloadCmd:  cfg.ReloadCmd,
		installCmd: cfg.VectorInstallCmd,
	}
}

var _versionRe = regexp.MustCompile(`\d+\.\d+(\.\d+)?`)

// Version returns the installed Vector semver (e.g. "0.41.1"), parsed from
// `vector --version`. "" if Vector isn't installed / can't be read.
func (v *Vector) Version(ctx context.Context) string {
	out, err := exec.CommandContext(ctx, v.bin, "--version").Output()
	if err != nil {
		return ""
	}
	return _versionRe.FindString(string(out))
}

// HasInstaller reports whether an install command is configured (auto-update).
func (v *Vector) HasInstaller() bool { return len(v.installCmd) > 0 }

// Install runs the configured install command with {version} substituted, to
// bring Vector to the desired version. Caller restarts/reloads afterwards.
func (v *Vector) Install(ctx context.Context, version string) error {
	if len(v.installCmd) == 0 {
		return fmt.Errorf("no VECTOR_INSTALL_CMD configured")
	}
	args := make([]string, len(v.installCmd))
	for i, a := range v.installCmd {
		args[i] = strings.ReplaceAll(a, "{version}", version)
	}
	cmd := exec.CommandContext(ctx, args[0], args[1:]...)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("%w: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

// Apply validates the candidate config, and only if it is valid atomically
// swaps it into place and reloads Vector. A validation failure leaves the
// running config untouched and returns the validator output — so a bad config
// can never take down a running pipeline.
func (v *Vector) Apply(ctx context.Context, configYAML string) error {
	dir := filepath.Dir(v.configPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("mkdir config dir: %w", err)
	}

	// Write the candidate to a temp file alongside the target.
	tmp, err := os.CreateTemp(dir, ".vortexflow-*.yaml")
	if err != nil {
		return fmt.Errorf("create temp config: %w", err)
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath) // no-op after a successful rename
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return fmt.Errorf("chmod temp config: %w", err)
	}
	if _, err := tmp.WriteString(configYAML); err != nil {
		tmp.Close()
		return fmt.Errorf("write temp config: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("close temp config: %w", err)
	}

	// Validate before swapping — the whole point of the agent.
	if out, err := v.validate(ctx, tmpPath); err != nil {
		return &ValidateError{Output: out, Err: err}
	}

	// Atomic swap, then reload.
	if err := os.Rename(tmpPath, v.configPath); err != nil {
		return fmt.Errorf("swap config into place: %w", err)
	}
	if err := v.reload(ctx); err != nil {
		return fmt.Errorf("reload vector: %w", err)
	}
	return nil
}

func (v *Vector) validate(ctx context.Context, path string) (string, error) {
	cmd := exec.CommandContext(ctx, v.bin, "validate", path)
	out, err := cmd.CombinedOutput()
	return strings.TrimSpace(string(out)), err
}

func (v *Vector) reload(ctx context.Context) error {
	if len(v.reloadCmd) == 0 {
		return nil
	}
	cmd := exec.CommandContext(ctx, v.reloadCmd[0], v.reloadCmd[1:]...)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("%w: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

// ValidateError signals that the candidate config failed `vector validate`. The
// running config is unchanged when this is returned.
type ValidateError struct {
	Output string
	Err    error
}

func (e *ValidateError) Error() string {
	if e.Output != "" {
		return "vector validate failed: " + e.Output
	}
	return "vector validate failed: " + e.Err.Error()
}
