/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: in handoff mode FastAPI serves these files itself, so the
  // analyst runs one container instead of two processes.
  output: "export",
  reactStrictMode: true,
  images: { unoptimized: true },
};

export default nextConfig;
