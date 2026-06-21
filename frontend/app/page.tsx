import Footer from "@/components/Footer";
import HomeClient from "@/components/HomeClient";

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col pt-[76px] relative">
      <HomeClient />
      <Footer />
    </div>
  );
}
