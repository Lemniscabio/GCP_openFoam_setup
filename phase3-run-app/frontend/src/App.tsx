function App() {
  return (
    <main className="app">
      <div className="bg" aria-hidden="true" />
      <header className="header">
        <div className="brand">
          <div className="brand-mark">OF</div>
          <div className="brand-name">
            OpenFOAM <span>Batch</span>
          </div>
        </div>
        <nav className="tabs" aria-label="Primary">
          <button className="tab on" type="button">
            Upload
          </button>
          <button className="tab" type="button">
            Cases
          </button>
          <button className="tab" type="button">
            Run
          </button>
          <button className="tab" type="button">
            Runs
          </button>
        </nav>
      </header>

      <section className="stage">
        <article className="panel">
          <div className="panel-head">
            <div className="ph-num">1</div>
            <div className="ph-text">
              <h1 className="ph-title">Frontend scaffold ready</h1>
              <p className="ph-sub">Task 1 design-system shell only.</p>
            </div>
          </div>
          <div className="panel-body">
            <button className="drop" type="button">
              <span className="drop-icon" aria-hidden="true">
                +
              </span>
              <span className="drop-text">
                <strong>Drop zone class</strong>
                <span>Reusable styling is available for the upload view.</span>
              </span>
            </button>
            <div className="segmented two" role="tablist" aria-label="Example mode">
              <button className="seg-opt on" type="button">
                Single
              </button>
              <button className="seg-opt" type="button">
                Multi
              </button>
            </div>
            <div className="chips">
              <span className="chip">case-A</span>
              <span className="chip">c2d-highcpu-16</span>
            </div>
          </div>
          <footer className="panel-foot terminal-footer">
            <div className="foot-bar">
              <span className="foot-label">Terminal</span>
              <div className="foot-actions">
                <button className="foot-btn" type="button">
                  Save .sh
                </button>
                <button className="foot-btn primary" type="button">
                  Copy
                </button>
              </div>
            </div>
            <pre className="foot-code">npm run build</pre>
          </footer>
        </article>
      </section>
    </main>
  )
}

export default App
