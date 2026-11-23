import { useState, type CSSProperties } from 'react';

// Mirrors the static loader in index.html (which owns the boot-loader CSS) so the
// handoff is seamless; the negative offset resumes its animations instead of restarting them.
export const AppLoader = () => {
  const [style] = useState(
    () => ({ '--boot-t': `${-Math.round(performance.now())}ms` }) as CSSProperties
  );

  return (
    <div className="boot-loader" role="status" style={style}>
      <div className="boot-loader__wave" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="boot-loader__name" aria-hidden="true">AI Subs</div>
      <div className="boot-loader__hint" aria-hidden="true">Waking up the server…</div>
      <span className="boot-loader__sr">Loading AI Subs</span>
    </div>
  );
};
