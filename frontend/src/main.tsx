import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { AppStoreProvider } from './store/AppStore'
import { AgentStoreProvider } from './store/AgentStore'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppStoreProvider>
      <AgentStoreProvider>
        <App />
      </AgentStoreProvider>
    </AppStoreProvider>
  </React.StrictMode>,
)
