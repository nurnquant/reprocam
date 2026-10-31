// Lumen & Loom practice store. Fictional brand, built as ReproCam's app under test.
//
// Three bugs are planted on purpose. Each is switched off when the build flag is set:
//   ?fixed=1  -> fixed build (remembered in localStorage)
//   ?fixed=0  -> back to the buggy build
// Search this file for "BUG 1", "BUG 2", "BUG 3".

const params = new URLSearchParams(location.search);
if (params.get("fixed") === "1") localStorage.setItem("ll_fixed", "1");
if (params.get("fixed") === "0") localStorage.removeItem("ll_fixed");
const FIXED = localStorage.getItem("ll_fixed") === "1";

// Prices in cents.
const PRODUCTS = [
  { id: "ember-dome", name: "Ember Dome Table Lamp", kind: "Lamp", price: 8900,
    swatch: ["#f2b46d", "#8a3f1d"], blurb: "Hand-blown amber glass over a walnut base. Warm, low glow for reading corners." },
  { id: "reed-arc", name: "Reed Arc Floor Lamp", kind: "Lamp", price: 14500,
    swatch: ["#e8dcc4", "#4b5a3a"], blurb: "A slim brass arc with a woven reed shade that throws soft, striped light." },
  { id: "pebble-light", name: "Pebble Night Light", kind: "Lamp", price: 1850,
    swatch: ["#f6efe2", "#b9a88c"], blurb: "A palm-sized stone-glass glow for hallways and nurseries." },
  { id: "saltmarsh-throw", name: "Saltmarsh Wool Throw", kind: "Textile", price: 6400,
    swatch: ["#9fb3ad", "#3c4f53"], blurb: "Loose-weave lambswool in the greys and greens of a tidal marsh." },
  { id: "linen-towels", name: "Linen Tea Towels, Set of 2", kind: "Textile", price: 2760,
    swatch: ["#efe4d0", "#c77d4a"], blurb: "Stonewashed linen with a rust selvedge stripe. Softer every wash." },
  { id: "indigo-cushion", name: "Indigo Weave Cushion Cover", kind: "Textile", price: 3200,
    swatch: ["#5b6f9e", "#1f2a4a"], blurb: "Plant-dyed indigo cotton on a hand loom, 45 x 45 cm." },
];

const PROMOS = { GLOW20: 2000 }; // flat $20 off

const productById = (id) => PRODUCTS.find((p) => p.id === id);

function money(cents) {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

// ---------- cart state ----------

function loadCart() {
  try {
    return JSON.parse(localStorage.getItem("ll_cart")) || { items: {}, promos: [] };
  } catch {
    return { items: {}, promos: [] };
  }
}

function saveCart(cart) {
  localStorage.setItem("ll_cart", JSON.stringify(cart));
  renderCartCount();
}

function addToCart(id) {
  const cart = loadCart();
  cart.items[id] = (cart.items[id] || 0) + 1;
  saveCart(cart);
}

function stepQuantity(id, delta) {
  const cart = loadCart();
  const qty = cart.items[id] || 0;
  if (FIXED) {
    cart.items[id] = Math.max(1, qty + delta);
  } else {
    // BUG 2: the stepper can go down to 0 and the line stays in the cart.
    cart.items[id] = Math.max(0, qty + delta);
  }
  saveCart(cart);
}

function removeLine(id) {
  const cart = loadCart();
  delete cart.items[id];
  saveCart(cart);
}

function applyPromo(raw) {
  const code = raw.trim().toUpperCase();
  const cart = loadCart();
  if (!PROMOS[code]) return { ok: false, msg: "That code isn't valid." };
  if (FIXED && cart.promos.includes(code)) return { ok: false, msg: `${code} is already applied.` };
  // BUG 1: nothing stops the same code being applied again and again.
  cart.promos.push(code);
  saveCart(cart);
  return { ok: true, msg: `${code} applied: ${money(PROMOS[code])} off.` };
}

function totals(cart) {
  let subtotal = 0;
  const lines = [];
  for (const [id, qty] of Object.entries(cart.items)) {
    const p = productById(id);
    if (!p) continue;
    // BUG 2 (cont.): a line at quantity 0 is still billed as one unit.
    const billed = FIXED ? qty : Math.max(qty, 1);
    lines.push({ product: p, qty, lineTotal: p.price * billed });
    subtotal += p.price * billed;
  }
  let discount = cart.promos.reduce((sum, code) => sum + (PROMOS[code] || 0), 0);
  if (FIXED) discount = Math.min(discount, subtotal);
  return { lines, subtotal, discount, total: subtotal - discount };
}

// ---------- shipping zone lookup (checkout) ----------

const ZONES = {
  1: "Northeast", 2: "Mid-Atlantic", 3: "Southeast", 4: "Great Lakes", 5: "Plains",
  6: "Central", 7: "South", 8: "Mountain", 9: "Pacific",
};
if (FIXED) ZONES[0] = "New England";

function lookupShippingZone(zip) {
  return new Promise((resolve) => {
    setTimeout(() => {
      const zone = ZONES[zip[0]];
      // BUG 3: no zone for ZIPs starting with "0" and no else branch,
      // so the promise never settles and checkout spins forever.
      if (zone) resolve(zone);
    }, 400);
  });
}

// ---------- rendering ----------

const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "testid") node.dataset.testid = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

function swatch(p, size = "") {
  const s = el("div", { class: `swatch ${size}`, "aria-hidden": "true" });
  s.style.setProperty("--a", p.swatch[0]);
  s.style.setProperty("--b", p.swatch[1]);
  return s;
}

function renderCartCount() {
  const node = $('[data-testid="cart-count"]');
  if (!node) return;
  const n = Object.values(loadCart().items).reduce((a, b) => a + b, 0);
  node.textContent = String(n);
}

function renderBuildBadge() {
  const node = $('[data-testid="build-mode"]');
  if (node) node.textContent = FIXED ? "build: fixed" : "build: buggy";
}

function renderList() {
  const grid = $('[data-testid="product-grid"]');
  for (const p of PRODUCTS) {
    grid.append(
      el("a", { class: "card", href: `product.html?id=${p.id}`, testid: `product-card-${p.id}` },
        swatch(p),
        el("span", { class: "kind" }, p.kind),
        el("span", { class: "name", testid: "product-name" }, p.name),
        el("span", { class: "price", testid: "product-price" }, money(p.price)),
      ),
    );
  }
}

function renderDetail() {
  const p = productById(params.get("id")) || PRODUCTS[0];
  document.title = `${p.name} · Lumen & Loom`;
  const added = el("p", { class: "note", testid: "added-message", hidden: "" },
    "Added to your basket. ", el("a", { href: "cart.html", testid: "view-cart" }, "View basket"));
  $('[data-testid="product-detail"]').append(
    swatch(p, "large"),
    el("div", { class: "detail-copy" },
      el("span", { class: "kind" }, p.kind),
      el("h1", { testid: "product-title" }, p.name),
      el("p", { class: "price", testid: "product-price" }, money(p.price)),
      el("p", { class: "blurb" }, p.blurb),
      el("button", { class: "btn", testid: "add-to-cart", onclick: () => { addToCart(p.id); added.hidden = false; } },
        "Add to basket"),
      added,
    ),
  );
}

function renderCart() {
  const root = $('[data-testid="cart"]');
  root.replaceChildren();
  const cart = loadCart();
  const t = totals(cart);

  if (!t.lines.length) {
    root.append(el("p", { class: "empty", testid: "cart-empty" }, "Your basket is empty. ",
      el("a", { href: "index.html" }, "Browse the shop")));
    return;
  }

  const list = el("ul", { class: "lines" });
  for (const { product: p, qty, lineTotal } of t.lines) {
    const atMin = FIXED && qty <= 1;
    list.append(
      el("li", { class: "line", testid: `cart-line-${p.id}` },
        swatch(p, "small"),
        el("span", { class: "name", testid: "line-name" }, p.name),
        el("span", { class: "stepper" },
          el("button", { class: atMin ? "step at-min" : "step", testid: "qty-minus", "aria-label": `Decrease ${p.name}`,
            onclick: () => { stepQuantity(p.id, -1); renderCart(); } }, "−"),
          el("span", { class: "qty", testid: "line-qty" }, String(qty)),
          el("button", { class: "step", testid: "qty-plus", "aria-label": `Increase ${p.name}`,
            onclick: () => { stepQuantity(p.id, 1); renderCart(); } }, "+"),
        ),
        el("span", { class: "line-total", testid: "line-total" }, money(lineTotal)),
        el("button", { class: "link", testid: "line-remove", onclick: () => { removeLine(p.id); renderCart(); } }, "Remove"),
      ),
    );
  }

  const promoMsg = el("p", { class: "note", testid: "promo-message", role: "status" });
  const promoInput = el("input", { id: "promo", testid: "promo-input", placeholder: "Promo code", autocomplete: "off" });
  const promoForm = el("form", { class: "promo", testid: "promo-form", onsubmit: (e) => {
    e.preventDefault();
    const r = applyPromo(promoInput.value);
    renderCart();
    const msg = $('[data-testid="promo-message"]');
    msg.textContent = r.msg;
    msg.classList.toggle("error", !r.ok);
  } },
    el("label", { for: "promo" }, "Promo code"),
    promoInput,
    el("button", { class: "btn ghost", type: "submit", testid: "promo-apply" }, "Apply"),
  );

  root.append(
    list,
    el("div", { class: "summary" },
      promoForm,
      promoMsg,
      el("dl", {},
        el("dt", {}, "Subtotal"), el("dd", { testid: "cart-subtotal" }, money(t.subtotal)),
        el("dt", {}, "Discount"), el("dd", { testid: "discount-total" }, money(-t.discount)),
        el("dt", {}, "Shipping"), el("dd", {}, "Free"),
        el("dt", { class: "total" }, "Total"), el("dd", { class: "total", testid: "order-total" }, money(t.total)),
      ),
      el("a", { class: "btn", href: "checkout.html", testid: "checkout-button" }, "Checkout"),
    ),
  );
}

function renderCheckout() {
  const t = totals(loadCart());
  $('[data-testid="checkout-total"]').textContent = money(t.total);
  const form = $('[data-testid="checkout-form"]');
  const error = $('[data-testid="checkout-error"]');
  const button = $('[data-testid="place-order"]');
  const spinner = $('[data-testid="place-order-spinner"]');

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const zip = form.elements.zip.value.trim();
    if (!/^\d{5}$/.test(zip)) {
      error.textContent = "Enter a 5-digit ZIP code.";
      return;
    }
    error.textContent = "";
    button.disabled = true;
    spinner.hidden = false;

    const zone = await lookupShippingZone(zip);
    await new Promise((r) => setTimeout(r, 300)); // "payment"

    const order = {
      number: `LL-${Math.floor(100000 + Math.random() * 900000)}`,
      total: t.total,
      zone,
      name: form.elements.name.value.trim(),
    };
    localStorage.setItem("ll_last_order", JSON.stringify(order));
    localStorage.removeItem("ll_cart");
    location.href = "confirmation.html";
  });
}

function renderConfirmation() {
  const order = JSON.parse(localStorage.getItem("ll_last_order") || "null");
  if (!order) return;
  $('[data-testid="order-number"]').textContent = order.number;
  $('[data-testid="confirmation-total"]').textContent = money(order.total);
  $('[data-testid="confirmation-zone"]').textContent = order.zone;
}

const PAGES = {
  list: renderList,
  detail: renderDetail,
  cart: renderCart,
  checkout: renderCheckout,
  confirmation: renderConfirmation,
};

document.addEventListener("DOMContentLoaded", () => {
  renderCartCount();
  renderBuildBadge();
  PAGES[document.body.dataset.page]?.();
});
