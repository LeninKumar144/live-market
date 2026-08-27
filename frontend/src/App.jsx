import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import DashboardLayout from "./components/DashboardLayout.jsx";
import UnderlyingDashboard from "./pages/UnderlyingDashboard.jsx";
import StockOptionsLiquidity from "./pages/StockOptionsLiquidity.jsx";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<DashboardLayout />}>
          <Route path="/" element={<Navigate to="/nifty" replace />} />
          <Route path="/nifty" element={<UnderlyingDashboard />} />
          <Route path="/banknifty" element={<UnderlyingDashboard />} />
          <Route path="/sensex" element={<UnderlyingDashboard />} />
          <Route path="/mcx" element={<UnderlyingDashboard />} />
          <Route path="/stock-options" element={<StockOptionsLiquidity />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
