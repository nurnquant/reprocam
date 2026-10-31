// Planted-bug registry for the Lumen & Loom practice store.
//
// Each id is one planted bug; true = present in the buggy build. App code asks
// bug("id") at the exact spot where it misbehaves, so adding a bug is: one line here,
// one `if (bug("..."))` branch in app.js.
//
// Build flag (remembered in localStorage):
//   ?fixed=1  -> fixed build, every bug off
//   ?fixed=0  -> back to the buggy build
//   ?reset=1  -> clear basket, promos and last order (see below)
const BUGS = {
  neg_total: true, // promo GLOW20 can be applied repeatedly; total goes below $0
  qty_stepper: true, // "−" at quantity 1 gives 0 but the line is still charged
  zip_hang: true, // ZIPs starting with 0 leave "Place order" spinning forever
};

const params = new URLSearchParams(location.search);
if (params.get("fixed") === "1") localStorage.setItem("ll_fixed", "1");
if (params.get("fixed") === "0") localStorage.removeItem("ll_fixed");
const FIXED = localStorage.getItem("ll_fixed") === "1";

// ?reset=1 starts a clean session (for recordings and tests): empty basket, no promos, no
// last order. The build flag is kept. The parameter is then removed from the address bar.
if (params.get("reset") === "1") {
  for (const key of ["ll_cart", "ll_last_order"]) localStorage.removeItem(key);
  params.delete("reset");
  const query = params.toString();
  history.replaceState(null, "", location.pathname + (query ? `?${query}` : "") + location.hash);
}

function bug(id) {
  if (!(id in BUGS)) throw new Error(`unknown bug id: ${id}`);
  return !FIXED && BUGS[id];
}
