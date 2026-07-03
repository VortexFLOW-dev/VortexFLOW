// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Command vortexflow-agent runs on a Vector host and keeps the host's Vector
// config converged to the stream config published by VortexFlow.
//
// It authenticates with a per-agent token (minted at registration), polls the
// control plane for its stream's config, validates each new generation with
// `vector validate`, atomically swaps it into place, reloads Vector, and reports
// the applied generation + health back.
package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
)

// version is set at build time via -ldflags "-X main.version=...".
var version = "dev"

func main() {
	log.SetFlags(log.LstdFlags | log.LUTC)
	log.Printf("vortexflow-agent %s", version)

	cfg, err := LoadConfig()
	if err != nil {
		log.Fatalf("config error: %v", err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	client, err := NewClient(cfg)
	if err != nil {
		log.Fatalf("client error: %v", err)
	}
	agent := NewAgent(cfg, client, NewVector(cfg))
	agent.Run(ctx)

	os.Exit(0)
}
