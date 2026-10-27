import { html, render } from './lib/preact.js';
import { App } from './views/app.js';

render(html`<${App} />`, document.getElementById('app'));
