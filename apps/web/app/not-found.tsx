import Link from "next/link";

export default function NotFound() {
  return (
    <main className="shell page">
      <div className="panel">
        <div className="panel-body">
          <div className="eyebrow">404</div>
          <h1 style={{ margin: "8px 0 10px" }}>Nothing to investigate here</h1>
          <p className="muted" style={{ maxWidth: "56ch" }}>
            That page does not exist. The incident queue is the place to start.
          </p>
          <p style={{ marginTop: 18 }}>
            <Link className="btn" href="/">
              Back to incidents
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
