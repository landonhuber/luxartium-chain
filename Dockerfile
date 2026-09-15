# syntax=docker/dockerfile:1
FROM golang:1.26.8-bookworm@sha256:9fdc884aacc3bec89b20ffc69f4bb369c78210e3e4f600387b5128b12c199f81 AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=4
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY app ./app
COPY cmd ./cmd
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go test -mod=readonly -p 4 ./... && \
    go build -mod=readonly -p 4 -trimpath -ldflags='-s -w -X github.com/cosmos/cosmos-sdk/version.Name=luxartium -X github.com/cosmos/cosmos-sdk/version.AppName=luxartiumd -X github.com/cosmos/cosmos-sdk/version.Version=0.1.0' -o /luxartiumd ./cmd/luxartiumd

FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171
RUN useradd --uid 10001 --create-home luxartium && mkdir /chain && chown luxartium:luxartium /chain && chmod 700 /chain
COPY --from=build /luxartiumd /usr/local/bin/luxartiumd
USER 10001:10001
WORKDIR /chain
ENV HOME=/home/luxartium
ENTRYPOINT ["luxartiumd"]
CMD ["start", "--home", "/chain"]
