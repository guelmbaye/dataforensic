/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The only images shipped are the brand assets, already sized. Serving them
  // unoptimised keeps sharp out of the standalone runtime image, which is one
  // less thing that can fail in a container that otherwise needs nothing.
  images: { unoptimized: true },
  // Standalone output is only useful for the container image. Enabling it
  // unconditionally would break `npm start` for anyone running locally.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
};

export default nextConfig;
