import { Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from '@/components/layout/app-layout'
import { WorkspaceGate } from '@/components/layout/workspace-gate'
import { NotFoundPage } from '@/routes/not-found-page'
import { OrganizationsPage } from '@/routes/organizations-page'
import { OverviewPage } from '@/routes/overview-page'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* A first-time user lands on onboarding here; an owner lands on their titles. */}
        <Route index element={<WorkspaceGate />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="organizations" element={<OrganizationsPage />} />
        <Route path="home" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
