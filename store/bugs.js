// Planted-bug registry for the Lumen & Loom practice store.
//
// Each id is one planted bug. `set` says who sees it:
//   demo      the public store and the 3 sample recordings
//   training  only with ?train=1: bugs that generate judge training data (M9) and are never
//             used to evaluate it, so demo bugs stay held out
// App code asks bug("id") at the exact spot where it misbehaves, so adding a bug is: one line
// here, one `if (bug("..."))` branch in app.js.
//
// Flags (remembered in localStorage):
//   ?fixed=1  -> fixed build, every bug off        ?fixed=0  -> back to the buggy build
//   ?train=1  -> training bugs on as well          ?train=0  -> demo bugs only
//   ?reset=1  -> clear basket, promos and last order (see below)
const BUGS = {
  neg_total: { on: true, set: "demo" }, // promo GLOW20 can be applied repeatedly; total goes below $0
  qty_stepper: { on: true, set: "demo" }, // "−" at quantity 1 gives 0 but the line is still charged
  zip_hang: { on: true, set: "demo" }, // ZIPs starting with 0 leave "Place order" spinning forever

  count_after_remove: { on: true, set: "training" }, // basket badge still counts a removed line
  subtotal_rounding: { on: true, set: "training" }, // lines with quantity 3+ are rounded to whole dollars
  detail_price: { on: true, set: "training" }, // the cushion's detail page shows $23.00 (list: $32.00)
  confirm_total_zero: { on: true, set: "training" }, // confirmation page says $0.00 was charged
  remove_wrong_line: { on: true, set: "training" }, // Remove deletes the first line, not the clicked one
};

const params = new URLSearchParams(location.search);
if (params.get("fixed") === "1") localStorage.setItem("ll_fixed", "1");
if (params.get("fixed") === "0") localStorage.removeItem("ll_fixed");
if (params.get("train") === "1") localStorage.setItem("ll_train", "1");
if (params.get("train") === "0") localStorage.removeItem("ll_train");
const FIXED = localStorage.getItem("ll_fixed") === "1";
const TRAIN = localStorage.getItem("ll_train") === "1";

function bug(id) {
  const entry = BUGS[id];
  if (!entry) throw new Error(`unknown bug id: ${id}`);
  if (FIXED || !entry.on) return false;
  return entry.set === "demo" || TRAIN;
}
