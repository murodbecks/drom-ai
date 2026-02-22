# Dröm AI frontend

## Installation and run guide

### 1) Prerequisites

Make sure these are installed:

- Node.js `>=18` (recommended: latest LTS)
- npm (comes with Node.js)
- Git

Check versions:

```bash
node -v
npm -v
git --version
```

### 2) Clone the repository

```bash
git clone https://github.com/murodbecks/drom-ai.git
cd drom-ai/frontend
```

### 3) Install dependencies

```bash
npm install
```

### 4) Start development server

```bash
npm run dev
```

Open the URL shown in terminal (usually `http://localhost:5173`).

### 5) Build for production

```bash
npm run build
```

The production output is generated in the `dist/` folder.

### 6) Preview production build locally

```bash
npm run preview
```

Open the preview URL shown in terminal.

### 7) Share on local network (optional)

To make the app reachable by other devices on the same Wi-Fi:

```bash
npm run dev -- --host
```

Then share your machine's local IP URL (for example `http://192.168.1.20:5173`).

### Troubleshooting

- If install fails, remove `node_modules` and `package-lock.json`, then run `npm install` again.
- If port `5173` is busy, Vite will suggest another port automatically.
- If `node` command is not found, reinstall Node.js and restart terminal.
