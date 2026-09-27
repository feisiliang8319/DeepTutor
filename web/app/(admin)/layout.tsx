import AccountShell from "@/components/layout/AccountShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <CapabilityAccessProvider>
      <AccountShell area="management">{children}</AccountShell>
    </CapabilityAccessProvider>
  );
}
