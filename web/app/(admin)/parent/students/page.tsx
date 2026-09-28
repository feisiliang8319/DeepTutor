import AccountManager from "@/components/teaching/AccountManager";

export default function ParentStudentsPage() {
  return <div className="h-full overflow-auto"><div className="mx-auto max-w-5xl px-5 py-8 md:px-10 md:py-12">
    <AccountManager parent standalone/>
  </div></div>;
}
