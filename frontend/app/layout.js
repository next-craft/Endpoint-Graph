import './globals.css'   // resolves to frontend/app/globals.css

export const metadata = {
  title: 'EndpointGraph',
  description: 'API consumer dependency graph',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
