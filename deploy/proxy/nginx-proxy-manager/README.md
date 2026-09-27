# Nginx Proxy Manager

Planhaven expects a reverse proxy in front of it that handles HTTPS (SECURITY.md §9).

## Proxy host

1. **Hosts → Proxy Hosts → Add Proxy Host.**
2. **Details:**
   - *Domain Names:* your Planhaven address, e.g. `projects.example.com`
   - *Scheme:* `http`
   - *Forward Hostname / IP:* the Planhaven container's name (if both containers share a custom
     Docker network) or your server's IP
   - *Forward Port:* `8080`
   - *Websockets Support:* **on** (needed for live updates and co-editing, ADR 0011)
   - *Block Common Exploits:* on
3. **SSL:** request a certificate, then turn on *Force SSL*, *HTTP/2 Support* and *HSTS
   Enabled*.
4. **Advanced → Custom Nginx Configuration:**

   ```nginx
   # Uploads (match MAX_UPLOAD_MB, plus a little room)
   client_max_body_size 110m;
   # Long-lived connections (live updates, AI connector)
   proxy_read_timeout 300s;
   proxy_buffering off;
   ```

NPM already sends `X-Forwarded-For` and `X-Forwarded-Proto`, which Planhaven reads **only** from
addresses listed in `TRUSTED_PROXIES`.

## Planhaven settings

- `BASE_URL`: exactly the address above, with `https://`.
- `TRUSTED_PROXIES`: the address Planhaven sees NPM connecting from. On a custom Docker network
  that's the network's range (Docker → the network → Subnet, e.g. `172.18.0.0/16`).

Check: after signing in, Account → *Signed-in devices* should show **your** public IP, not NPM's.
If it shows NPM's address, `TRUSTED_PROXIES` is wrong. If it shows a CDN or tunnel address, the
layer in front of NPM must pass the client address (e.g. Cloudflare: NPM's real-IP settings for
Cloudflare ranges).

## Don't

- Don't put forward-auth (Authelia/Authentik proxy auth, Cloudflare Access) in front of
  Planhaven: the iPhone Shortcut, calendar feed and AI connector can't pass it (ADR 0009).
- Don't expose port 8080 to the internet directly.
