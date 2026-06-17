/**
 * main.tsx — Vite entry point. Mounts the React app into the DOM.
 * This is identical to the standard Vite React template.
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
