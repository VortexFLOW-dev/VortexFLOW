BINARY := vortexflow-agent
VERSION ?= dev
LDFLAGS := -s -w -X main.version=$(VERSION)

# Targets to cross-compile for release. Vector runs on Linux hosts in practice;
# darwin is included for local dev.
PLATFORMS := linux/amd64 linux/arm64 darwin/amd64 darwin/arm64

.PHONY: build vet fmt test clean release

build:
	CGO_ENABLED=0 go build -ldflags "$(LDFLAGS)" -o bin/$(BINARY) .

vet:
	go vet ./...

fmt:
	gofmt -w .

test:
	go test ./...

clean:
	rm -rf bin dist

# Static, stripped binaries for each platform under dist/.
release: $(PLATFORMS)

$(PLATFORMS):
	@os=$(word 1,$(subst /, ,$@)); arch=$(word 2,$(subst /, ,$@)); \
	echo "building $$os/$$arch"; \
	CGO_ENABLED=0 GOOS=$$os GOARCH=$$arch \
	  go build -ldflags "$(LDFLAGS)" -o dist/$(BINARY)-$$os-$$arch .
