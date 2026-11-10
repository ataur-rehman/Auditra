import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import { LiveProvider } from './lib/live'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Incidents from './pages/Incidents'
import IncidentDetail from './pages/IncidentDetail'
import Employees from './pages/Employees'
import EmployeeDetail from './pages/EmployeeDetail'
import ActivityPage from './pages/Activity'
import Records from './pages/Records'
import Reports from './pages/Reports'
import AdminEmployees from './pages/admin/AdminEmployees'
import Catalogue from './pages/admin/Catalogue'
import Rules from './pages/admin/Rules'
import Agents from './pages/admin/Agents'
import Users from './pages/admin/Users'
import Audit from './pages/admin/Audit'
import EmployeePortal from './pages/EmployeePortal'

function Protected({ children, admin }) {
  const { user, ready, isAdmin, isEmployee } = useAuth()
  if (!ready) return <Spinner label="Starting console" />
  if (!user) return <Navigate to="/login" replace />
  // Employees only have their own portal; the monitoring console is for officers and admins.
  if (isEmployee) return <Navigate to="/me" replace />
  if (admin && !isAdmin) return <Navigate to="/" replace />
  return children
}

function EmployeeOnly({ children }) {
  const { user, ready, isEmployee } = useAuth()
  if (!ready) return <Spinner label="Starting" />
  if (!user) return <Navigate to="/login" replace />
  if (!isEmployee) return <Navigate to="/" replace />
  return children
}

export default function App() {
  const { user, isEmployee } = useAuth()
  return (
    <LiveProvider enabled={Boolean(user) && !isEmployee}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/me" element={<EmployeeOnly><EmployeePortal /></EmployeeOnly>} />
        <Route element={<Protected><Layout /></Protected>}>
          <Route index element={<Overview />} />
          <Route path="incidents" element={<Incidents />} />
          <Route path="incidents/:id" element={<IncidentDetail />} />
          <Route path="employees" element={<Employees />} />
          <Route path="employees/:id" element={<EmployeeDetail />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="records" element={<Records />} />
          <Route path="reports" element={<Reports />} />
          <Route path="admin/employees" element={<Protected admin><AdminEmployees /></Protected>} />
          <Route path="admin/catalogue" element={<Protected admin><Catalogue /></Protected>} />
          <Route path="admin/rules" element={<Protected admin><Rules /></Protected>} />
          <Route path="admin/agents" element={<Protected admin><Agents /></Protected>} />
          <Route path="admin/users" element={<Protected admin><Users /></Protected>} />
          <Route path="admin/audit" element={<Protected admin><Audit /></Protected>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </LiveProvider>
  )
}
