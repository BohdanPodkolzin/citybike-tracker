// Soft colour blobs that drift slowly behind the page. Pure CSS (see styles.css):
// gradients that fade to transparent look blurred without an expensive blur
// filter, so it stays smooth on a phone. Disabled for "reduce motion".
export default function AnimatedBackground() {
  return (
    <div className="bg" aria-hidden="true">
      <span className="blob b1" />
      <span className="blob b2" />
      <span className="blob b3" />
      <span className="blob b4" />
    </div>
  );
}
