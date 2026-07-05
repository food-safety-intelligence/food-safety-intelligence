/**
 * The "Eatelligence" wordmark. "Eatelligence" = Eat + intelligence; the "Eat"
 * pun stem renders in the serif italic sage accent (sage-strong clears AA),
 * "elligence" inherits the surrounding text style. This emits inline text only —
 * the parent element controls size, weight, and colour of the rest — so the same
 * wordmark works in the header logo, a chat heading, or the entry popup.
 */
export function Wordmark() {
  return (
    <>
      <span className="serif italic text-sage-strong">Eat</span>elligence
    </>
  );
}
