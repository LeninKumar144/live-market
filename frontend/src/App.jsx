import { BrowserRouter, Routes, Route } from "react-router-dom";
import DashboardLayout from "./components/DashboardLayout.jsx";
import Home from "./pages/Home.jsx";
import StockOptionsLiquidity from "./pages/StockOptionsLiquidity.jsx";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<DashboardLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/stock-options" element={<StockOptionsLiquidity />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
