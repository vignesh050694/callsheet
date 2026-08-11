import { Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from '@/components/layout/app-layout'
import { WorkspaceGate } from '@/components/layout/workspace-gate'
import { AcceptInvitationPage } from '@/routes/accept-invitation-page'
import { MembersPage } from '@/routes/members-page'
import { NotFoundPage } from '@/routes/not-found-page'
import { OrganizationsPage } from '@/routes/organizations-page'
import { OverviewPage } from '@/routes/overview-page'
import { TitleSchedulePage } from '@/routes/title-schedule-page'
import { TitleSetupPage } from '@/routes/title-setup-page'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* A first-time user lands on onboarding here; an owner lands on their titles. */}
        <Route index element={<WorkspaceGate />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="members" element={<MembersPage />} />
        <Route path="titles/new" element={<TitleSetupPage />} />
        <Route path="titles/:titleId/schedule" element={<TitleSchedulePage />} />
        <Route path="invitations/accept" element={<AcceptInvitationPage />} />
        <Route path="organizations" element={<OrganizationsPage />} />
        <Route path="home" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
