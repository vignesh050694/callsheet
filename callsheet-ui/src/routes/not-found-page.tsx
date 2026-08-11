import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <section className="py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link to="/" className="text-brand-600 mt-4 inline-block text-sm hover:underline">
        Back to overview
      </Link>
    </section>
  )
}
