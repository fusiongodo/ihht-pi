<main>
  <h1>IHHT</h1>
  <ul>
    <li>
      <a href="/">Camera</a>
      <p>Live view. Set the bore, then record a sweep or a steady.</p>
    </li>
    <li>
      <a href="/label">Label</a>
      <p>Click the ball on each frame of a recording.</p>
    </li>
    <li>
      <a href="/play">Playback</a>
      <p>Play a labeled sweep at 2.5 fps with the click, glint, and HOG marks.</p>
    </li>
    <li>
      <a href="/annotate">Annotate</a>
      <p>Mark the ball on the still shots.</p>
    </li>
  </ul>
</main>

<style>
  :global(body) {
    margin: 0;
    background: #111;
    color: #eee;
    font-family: system-ui, sans-serif;
  }

  main {
    box-sizing: border-box;
    min-height: 100vh;
    padding: 28px 24px 40px;
  }

  h1 {
    margin: 0 0 28px;
    font-size: 1.4rem;
    font-weight: 650;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    max-width: 36rem;
  }

  li {
    margin: 0 0 22px;
  }

  a {
    color: #8cf;
    font-size: 1.35rem;
    font-weight: 650;
    text-decoration: none;
  }

  a:hover {
    text-decoration: underline;
  }

  p {
    margin: 6px 0 0;
    color: #bbb;
    line-height: 1.4;
  }
</style>
