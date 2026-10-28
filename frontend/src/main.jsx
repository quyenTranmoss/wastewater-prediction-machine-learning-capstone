//This file is the entry point of the React app. 
// It's the very first javascript file that runs when the application starts.

// imports modules, ReactDOM, and the main App component.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
