import type { ReactNode } from "react";
import { Link, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { homePathFor, useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import { EmptyState, LoadingBlock } from "./components/ui";
import type { Role } from "./lib/types";
import AccountDetail from "./pages/AccountDetail";
import Accounts from "./pages/Accounts";
import Cash from "./pages/Cash";
import Dashboard from "./pages/Dashboard";
import DemoWorkload from "./pages/DemoWorkload";
import ForgotPassword from "./pages/ForgotPassword";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import Register from "./pages/Register";
import ResetPassword from "./pages/ResetPassword";
import Transactions from "./pages/Transactions";
import Transfer from "./pages/Transfer";
import { StatementsPage, LoansPage } from "./pages/DigitalServices";
import { AdminAccessProvider } from "./pages/admin/access";
import AdminOverview from "./pages/admin/Overview";
import AdminProfile from "./pages/admin/AdminProfile";
import CustomerSupport from "./pages/admin/CustomerSupport";
import LoanDetail from "./pages/admin/LoanDetail";
import LoanQueue from "./pages/admin/LoanQueue";
import StatementOps from "./pages/admin/StatementOps";

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingBlock label="Checking your session…" />
      </div>
    );
  }
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** Client-side role gate for navigation only; every API enforces roles server-side. */
function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { session } = useAuth();
  if (!session) return null;
  if (session.user.role !== role) {
    return (
      <div className="card">
        <EmptyState
          title="Not available for your role"
          message="This page isn't part of your access profile."
          action={
            <Link to={homePathFor(session.user.role)} className="btn-primary">
              Go to my home page
            </Link>
          }
        />
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * Admin workspace guard: non-admins are sent to their own home page (no admin UI is rendered).
 * Navigation only; the Core and extension APIs enforce authorization server-side.
 */
function AdminOnly() {
  const { session } = useAuth();
  if (!session) return null;
  if (session.user.role !== "admin") return <Navigate to={homePathFor(session.user.role)} replace />;
  return (
    <AdminAccessProvider>
      <Outlet />
    </AdminAccessProvider>
  );
}

/** Retired admin/reviewer URLs: admins go to the new workspace, others to their home. */
function LegacyAdminRedirect() {
  const { session } = useAuth();
  if (!session) return null;
  return <Navigate to={session.user.role === "admin" ? "/admin" : homePathFor(session.user.role)} replace />;
}

function Home() {
  const { session } = useAuth();
  return <Navigate to={session ? homePathFor(session.user.role) : "/login"} replace />;
}

function NotFound() {
  return (
    <div className="card">
      <EmptyState
        title="Page not found"
        message="The page you're looking for doesn't exist."
        action={
          <Link to="/" className="btn-primary">
            Go home
          </Link>
        }
      />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Public (signed-out) pages: they call their APIs with skipAuthRedirect. */}
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Home />} />
        <Route path="/dashboard" element={<RequireRole role="customer"><Dashboard /></RequireRole>} />
        <Route path="/accounts" element={<RequireRole role="customer"><Accounts /></RequireRole>} />
        <Route path="/accounts/:id" element={<RequireRole role="customer"><AccountDetail /></RequireRole>} />
        <Route path="/transfer" element={<RequireRole role="customer"><Transfer /></RequireRole>} />
        <Route path="/cash" element={<RequireRole role="customer"><Cash /></RequireRole>} />
        <Route path="/transactions" element={<RequireRole role="customer"><Transactions /></RequireRole>} />
        <Route path="/profile" element={<RequireRole role="customer"><Profile /></RequireRole>} />
        <Route path="/statements" element={<RequireRole role="customer"><StatementsPage /></RequireRole>} />
        <Route path="/loans" element={<RequireRole role="customer"><LoansPage /></RequireRole>} />
        <Route path="/loan-review" element={<LegacyAdminRedirect />} />
        <Route path="/operations" element={<LegacyAdminRedirect />} />
        <Route path="/admin" element={<AdminOnly />}>
          <Route index element={<AdminOverview />} />
          <Route path="loans" element={<LoanQueue />} />
          <Route path="loans/:id" element={<LoanDetail />} />
          <Route path="statements" element={<StatementOps />} />
          <Route path="customers" element={<CustomerSupport />} />
          <Route path="profile" element={<AdminProfile />} />
          <Route path="*" element={<NotFound />} />
        </Route>
        <Route path="/demo-workload" element={<RequireRole role="demo"><DemoWorkload /></RequireRole>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
