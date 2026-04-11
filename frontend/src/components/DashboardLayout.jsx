import { NavLink, Outlet } from "react-router-dom";
import "./DashboardLayout.css";

function navClass({ isActive }) {
  return isActive ? "dash-nav__link dash-nav__link--active" : "dash-nav__link";
}

export default function DashboardLayout() {
  return (
    <div className="app-shell">
      <nav className="dash-nav" aria-label="Dashboard sections">
        <NavLink to="/" end className={navClass}>
          NIFTY OI &amp; hedging
        </NavLink>
        <NavLink to="/stock-options" className={navClass}>
          Stock options — liquidity
        </NavLink>
      </nav>
      <Outlet />
    </div>
  );
}
