import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "@fontsource/schibsted-grotesk/400.css";
import "@fontsource/schibsted-grotesk/500.css";
import "@fontsource/schibsted-grotesk/600.css";
import "@fontsource/schibsted-grotesk/700.css";
import "@fontsource/source-serif-4/400.css";
import "@fontsource/source-serif-4/400-italic.css";
import "@fontsource/source-serif-4/600.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
