const h = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const short = (value, count = 10) => value ? `${value.slice(0, count)}…${value.slice(-6)}` : "—";
const count = (value) => BigInt(value).toLocaleString("en-US");
export function luxar(value) {
  const n = BigInt(value);
  const fraction = (n % 1000000n).toString().padStart(6, "0").replace(/0+$/, "");
  return `${(n / 1000000n).toLocaleString("en-US")}${fraction ? "." + fraction : ""}`;
}
const coins = (items) => (items || []).map((c) => c.denom === "uluxar" ? `${luxar(c.amount)} LUXAR` : `${c.amount} ${c.denom}`).join(" + ") || "0 LUXAR";
const time = (value) => new Date(value).toLocaleString(undefined, {dateStyle: "medium", timeStyle: "medium"});
const age = (value) => {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 1000));
  return seconds < 60 ? `${seconds}s ago` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h ago` : `${Math.floor(seconds / 86400)}d ago`;
};
const link = (kind, value, label = short(value)) => `<a class="mono" href="#/${kind}/${encodeURIComponent(value)}" title="${h(value)}">${h(label)}</a>`;
const badge = (code) => `<span class="badge ${code === 0 ? "success" : "failed"}">${code === 0 ? "Success" : "Failed"}</span>`;
const type = (actions) => actions?.length ? actions.map((a) => a.split(".").pop().replace(/^Msg/, "")).join(", ") : "Transaction";
const empty = (message) => `<div class="empty"><span aria-hidden="true">◇</span><p>${h(message)}</p></div>`;
const heading = (eyebrow, title, description = "", aside = "") => `<div class="page-heading"><div><p class="eyebrow">${h(eyebrow)}</p><h1>${h(title)}</h1>${description ? `<p class="subtitle">${h(description)}</p>` : ""}</div>${aside}</div>`;
const panel = (title, body, action = "") => `<section class="panel"><div class="panel-heading"><h2>${h(title)}</h2>${action}</div>${body}</section>`;
const details = (rows) => `<dl class="details">${rows.map(([key, value]) => `<div><dt>${h(key)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
const blockTable = (blocks) => !blocks.length ? empty("No blocks are available yet.") : `<div class="table-scroll"><table><thead><tr><th>Block</th><th>Created</th><th>Transactions</th><th>Block hash</th></tr></thead><tbody>${blocks.map((b) => `<tr><td><span class="block-icon">▱</span>${link("block", b.height, count(b.height))}</td><td title="${h(time(b.time))}">${h(age(b.time))}</td><td>${h(b.transactions)}</td><td>${link("block", b.height, short(b.hash))}</td></tr>`).join("")}</tbody></table></div>`;
const txTable = (transactions) => !transactions.length ? empty("No indexed transactions to show yet.") : `<div class="table-scroll"><table><thead><tr><th>Transaction hash</th><th>Action</th><th>Block</th><th>Result</th></tr></thead><tbody>${transactions.map((tx) => `<tr><td>${link("tx", tx.hash)}</td><td>${h(type(tx.actions))}</td><td>${link("block", tx.height, count(tx.height))}</td><td>${badge(tx.code)}</td></tr>`).join("")}</tbody></table></div>`;

async function api(path) {
  const response = await fetch(`/api/${path}`, {signal: AbortSignal.timeout(30000)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The node could not answer this request.");
  return data;
}

function overview(data) {
  const blocks = data.blocks.items;
  return `<section class="hero"><div><p class="eyebrow">LUXARTIUM NETWORK</p><h1>Every block.<br>A shared record.</h1><p>Follow the network as it grows. Explore blocks,<br class="desktop-only"> trace transactions, and look up any account.</p><span class="hero-tag"><span class="live-dot"></span>${h(data.chain_id)}</span></div><div class="orbit" aria-hidden="true"><div class="orbit-ring one"></div><div class="orbit-ring two"></div><div class="orbit-ring three"></div><div class="orbit-core">L</div><span class="orbit-point p1"></span><span class="orbit-point p2"></span><span class="orbit-point p3"></span></div></section>
    <div class="stats"><section><span class="stat-label">LATEST BLOCK <span>↗</span></span><strong>${link("block", data.height, count(data.height))}</strong><small>Committed ${h(age(data.time))}</small></section><section class="supply-stat"><span class="stat-label">NATIVE SUPPLY <span>◈</span></span><strong>${h(luxar(data.supply.amount))}<em>LUXAR</em></strong><small>Current on-chain supply</small></section><section><span class="stat-label">ACTIVE VALIDATORS <span>◇</span></span><strong>${h(count(data.validators))}</strong><small>Local testnet consensus</small></section><section><span class="stat-label">INDEXED TRANSACTIONS <span>⇄</span></span><strong>${h(count(data.transactions.total))}</strong><small>Committed, including failed executions</small></section></div>
    <div class="section-intro"><div><p class="eyebrow">ON THE LEDGER</p><h2>Network activity</h2></div><span class="refresh-note"><span class="live-dot"></span> Refreshes every 6 seconds</span></div>
    ${panel("Latest blocks", blockTable(blocks.slice(0, 6)), '<a href="#/blocks" class="text-link">View all blocks ↗</a>')}
    ${panel("Latest transactions", txTable(data.transactions.items), '<a href="#/transactions" class="text-link">View all transactions ↗</a>')}
    <div class="network-note"><span>ⓘ</span><p>This is Luxartium’s local testnet. Balances and transactions are real records on this development chain. Test LUXAR has no monetary value.</p></div>`;
}

function blockView(data) {
  const b = data.header;
  const back = BigInt(b.height) > 1n ? `<a class="button secondary" href="#/block/${BigInt(b.height) - 1n}">← Previous block</a>` : "";
  return heading("BLOCK RECORD", `Block #${count(b.height)}`, time(b.time), back) + panel("Block details", details([
    ["Block hash", `<span class="mono wrap">${h(data.hash)}</span>`], ["Chain", h(b.chain_id)],
    ["Timestamp", h(time(b.time))], ["Transactions", h(data.transactions.length)],
    ["Proposer", `<span class="mono wrap">${h(b.proposer_address)}</span>`],
    ["Previous block hash", `<span class="mono wrap">${h(b.last_block_id.hash || "Genesis block")}</span>`],
    ["Application hash (header)", `<span class="mono wrap">${h(b.app_hash || "—")}</span>`],
  ])) + panel(`Transactions (${data.transactions.length})`, data.transactions.length ? `<ul class="record-list">${data.transactions.map((hash) => `<li>${link("tx", hash, hash)}<span>↗</span></li>`).join("")}</ul>` : empty("This block contains no transactions. It still advances the chain."));
}

function txView(data) {
  const response = data.tx_response;
  const tx = data.tx;
  const succeeded = Number(response.code) === 0;
  const messages = tx.body.messages;
  return heading("TRANSACTION RECORD", "Transaction details", "A committed transaction and its execution result.", badge(Number(response.code))) + panel("Overview", details([
    ["Transaction hash", `<span class="mono wrap">${h(response.txhash)}</span>`],
    ["Block", link("block", response.height, `#${count(response.height)}`)],
    ["Timestamp", h(time(response.timestamp))], ["Declared fee", h(coins(tx.auth_info.fee.amount))],
    ["Gas used / limit", `${h(count(response.gas_used))} / ${h(count(tx.auth_info.fee.gas_limit))}`],
    ["Memo", h(tx.body.memo || "No memo")],
    ...(!succeeded ? [["Execution error", `<span class="error-text">Code ${h(response.code)} · ${h(response.raw_log || response.codespace || "Execution failed")}</span>`]] : []),
  ])) + messages.map((message, index) => panel(`Message ${index + 1} · ${type([message["@type"]])}`, message["@type"] === "/cosmos.bank.v1beta1.MsgSend" ? `<div class="transfer-flow"><div><span class="eyebrow">FROM</span>${link("account", message.from_address, message.from_address)}</div><span class="flow-arrow" aria-hidden="true">→</span><div><span class="eyebrow">TO</span>${link("account", message.to_address, message.to_address)}</div></div><div class="transfer-amount"><span>${succeeded ? "Transferred amount" : "Attempted amount · transfer failed"}</span><strong>${h(coins(message.amount))}</strong></div>` : `<pre>${h(JSON.stringify(message, null, 2))}</pre>`)).join("") + `<details class="panel raw"><summary>View transaction JSON</summary><pre>${h(JSON.stringify(data, null, 2))}</pre></details>`;
}

function accountView(data) {
  return heading("ACCOUNT RECORD", "Account", "Available native balance and recent indexed activity.") + `<section class="account-card"><div><span class="eyebrow">LUXARTIUM ADDRESS</span><p class="mono wrap">${h(data.address)}</p></div><div><span class="eyebrow">AVAILABLE BALANCE</span><strong>${h(luxar(data.balance.amount))}<em>LUXAR</em></strong></div></section>` + panel("Recent account activity", txTable(data.transactions)) + `<p class="muted fine">Up to ${data.activity_limit} recent transactions indexed by sender or recipient. This includes fee-related activity and is not a complete account ledger. Bonded stake and unclaimed rewards are excluded from available balance.</p>`;
}

function boot() {
  const view = document.querySelector("#view");
  const notice = document.querySelector("#notice");
  const connection = document.querySelector("#connection");
  let generation = 0;
  let refreshing = false;
  let currentRoute = "";

  async function render(background = false) {
    if (background && refreshing) return;
    const route = location.hash.slice(1) || "/";
    const token = ++generation;
    refreshing = true;
    if (!background) {
      view.setAttribute("aria-busy", "true");
      view.innerHTML = '<div class="loading">Reading the network…</div>';
      notice.textContent = "";
    }
    currentRoute = route;
    const [pathname, query] = route.split("?");
    const parts = pathname.split("/").filter(Boolean);
    const category = parts[0] || "overview";
    // Preserve old operator bookmarks without serving private content from the explorer.
    if (["roadmap", "processes"].includes(category)) {
      location.replace(`http://admin.luxartium.localhost:4174/admin/#/${category}`);
      return;
    }
    const selected = category === "block" ? "blocks" : category === "tx" ? "transactions" : category;
    document.querySelectorAll("[data-nav]").forEach((el) => {
      if (el.dataset.nav === selected) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
    });
    document.querySelector("#page-label").textContent = ({overview: "Overview", blocks: "Blocks", transactions: "Transactions", block: "Block", tx: "Transaction", account: "Account", roadmap: "Roadmap", processes: "Processes"})[category] || "Explorer";
    document.title = `${document.querySelector("#page-label").textContent} · Luxartium Explorer`;
    try {
      let html;
      let overviewStatus;
      if (category === "overview" && parts.length === 0) {
        const data = await api("overview");
        html = overview(data);
        const stale = Date.now() - Date.parse(data.time) > 30000;
        overviewStatus = {text: data.catching_up ? "Node syncing" : stale ? "No recent blocks" : "Network live",
                          className: `connection ${data.catching_up || stale ? "warning" : "online"}`};
      } else if (category === "blocks" && parts.length === 1) {
        const before = new URLSearchParams(query).get("before");
        const data = await api("blocks" + (before ? `?before=${encodeURIComponent(before)}` : ""));
        html = heading("THE CHAIN", "Blocks", "An ordered record of the network, one block at a time.") + panel("Committed blocks", blockTable(data.items)) + `<div class="pagination"><a class="button secondary" href="#/blocks">↑ Latest blocks</a>${data.next_before ? `<a class="button" href="#/blocks?before=${data.next_before}">Older blocks →</a>` : ""}</div>`;
      } else if (category === "transactions" && parts.length === 1) {
        const page = new URLSearchParams(query).get("page") || "1";
        const data = await api(`transactions?page=${encodeURIComponent(page)}`);
        html = heading("ON-CHAIN ACTIVITY", "Transactions", `${count(data.total)} indexed transactions on this node.`) + panel("Committed transactions", txTable(data.items)) + `<div class="pagination">${data.page > 1 ? `<a class="button secondary" href="#/transactions?page=${data.page - 1}">← Newer</a>` : '<span></span>'}<span class="muted">Page ${data.page}</span>${BigInt(data.page * data.page_size) < BigInt(data.total) ? `<a class="button" href="#/transactions?page=${data.page + 1}">Older →</a>` : ""}</div>`;
      } else if (["block", "tx", "account"].includes(category) && parts.length === 2) {
        const data = await api(`${category}/${encodeURIComponent(parts[1])}`);
        html = ({block: blockView, tx: txView, account: accountView})[category](data);
      } else {
        throw new Error("That explorer page does not exist.");
      }
      if (token !== generation) return;
      view.innerHTML = html;
      notice.textContent = "";
      if (overviewStatus) {
        connection.textContent = overviewStatus.text;
        connection.className = overviewStatus.className;
      } else if (category !== "overview") {
        connection.textContent = "Node connected";
        connection.className = "connection online";
      }
    } catch (error) {
      if (token !== generation) return;
      const message = error.name === "TimeoutError" ? "The node took too long to respond. Try again." : error.message;
      if (background) {
        notice.innerHTML = `<div class="notice">${h(message)} Displayed data may be out of date. <button data-retry>Retry</button></div>`;
      } else {
        view.innerHTML = `<section class="error-state"><span class="eyebrow">RECORD UNAVAILABLE</span><h1>We couldn’t load that.</h1><p>${h(message)}</p><button data-retry>Try again</button><a class="button secondary" href="#/">Back to overview</a></section>`;
      }
      connection.textContent = "Query unavailable";
      connection.className = "connection warning";
    } finally {
      if (token === generation) {
        refreshing = false;
        view.setAttribute("aria-busy", "false");
      }
    }
  }

  document.querySelector("#search").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.querySelector("#search-input").value.trim();
    const error = document.querySelector("#search-error");
    error.textContent = "";
    let route;
    if (/^[1-9][0-9]{0,18}$/.test(input) && BigInt(input) <= 9223372036854775807n) route = `/block/${input}`;
    else if (/^[a-fA-F0-9]{64}$/.test(input)) route = `/tx/${input.toUpperCase()}`;
    else if (/^luxar1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{38}$/.test(input)) route = `/account/${input}`;
    else {
      error.textContent = "Enter a positive block height, a 64-character transaction hash, or a luxar1 account address.";
      return;
    }
    if (location.hash === "#" + route) render(); else location.hash = route;
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest(".skip")) {
      event.preventDefault();
      document.querySelector("#content").focus();
    }
    if (event.target.closest("[data-retry]")) render();
  });
  window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
  setInterval(() => {
    if (!document.hidden && (currentRoute === "/" || currentRoute === "/blocks" || currentRoute.startsWith("/account/"))) render(true);
  }, 6000);
  render();
}

if (typeof document !== "undefined") boot();
