import { NavLink, Outlet } from "react-router-dom";
import "./DashboardLayout.css";

function navClass({ isActive }) {
  return isActive ? "dash-nav__link dash-nav__link--active" : "dash-nav__link";
}

export default function DashboardLayout() {
  return (
    <div className="app-shell">
      <nav className="dash-nav" aria-label="Dashboard sections">
        <NavLink to="/nifty" className={navClass}>
          NIFTY
        </NavLink>
        <NavLink to="/banknifty" className={navClass}>
          Bank Nifty
        </NavLink>
        <NavLink to="/sensex" className={navClass}>
          SENSEX
        </NavLink>
        <NavLink to="/mcx" className={navClass}>
          MCX Crude
        </NavLink>
        <NavLink to="/stock-options" className={navClass}>
          Stock options
        </NavLink>
      </nav>
      <Outlet />
    </div>
  );
}
