import { createRoot } from "react-dom/client";

import { App } from "./App";
import { openShell } from "./store";
import { bootTheme } from "./theme";
import "./styles.css";

bootTheme();

const container = document.getElementById("root");
if (!container) throw new Error("缺少 #root 挂载点");

createRoot(container).render(<App />);

void openShell();
