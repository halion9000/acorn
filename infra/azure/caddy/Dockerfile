# Caddy with the Cloudflare DNS plug-in, so the certificate for the private address is proved through DNS (no open internet port needed).
FROM caddy:2.8-builder AS build
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.8
COPY --from=build /usr/bin/caddy /usr/bin/caddy
