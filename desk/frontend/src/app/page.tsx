"use client";

import { useState } from "react";

const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://prizmafinans-production.up.railway.app";

const FEATURES = [
  {
    icon: "💼",
    title: "Fatura & Ödeme Takibi",
    desc: "Gelen/kesilen/komisyon faturalarını yönetin. Kısmi ödemeler, e-fatura gönderimi ve ödeme talimatları tek ekranda.",
  },
  {
    icon: "📋",
    title: "HBF — Harcama Bildirimi",
    desc: "Çalışanlar masraflarını belgeler, müdür ve GM otomatik bilgilendirilir. Belge ekleme, çift onay, geri ödeme.",
  },
  {
    icon: "👥",
    title: "Personel & Bordro",
    desc: "Çalışan mastery, SGK kesintisi, net maaş hesaplama. Yan haklar, kariyer olayları ve belge yönetimi.",
  },
  {
    icon: "🗓️",
    title: "İzin Yönetimi",
    desc: "Yıllık, hastalık, mazeret ve doğum günü izinleri. Bakiye takibi, takvim görünümü, müdür bildirimleri.",
  },
  {
    icon: "✅",
    title: "Onay Akışı",
    desc: "İki kademeli onay: Müdür → Genel Müdür. Her adımda e-posta + sistem bildirimi. Tam iz kaydı.",
  },
  {
    icon: "📊",
    title: "Raporlar & Analiz",
    desc: "Gelir-gider, KDV, kasa/banka özetleri. Excel dışa aktarım. E-defter ve vergi raporu hazırlığı.",
  },
];

const PRICING = [
  {
    name: "Starter",
    price: "₺1.490",
    period: "/ay",
    features: ["5 kullanıcı", "Fatura & Ödeme", "Kasa & Banka", "Raporlar", "E-posta bildirimleri"],
    cta: "Başla",
    highlight: false,
  },
  {
    name: "Pro",
    price: "₺2.990",
    period: "/ay",
    features: ["15 kullanıcı", "Tüm Starter özellikleri", "HBF & Avans", "Personel & Bordro", "İzin Yönetimi", "Öncelikli destek"],
    cta: "En Popüler",
    highlight: true,
  },
  {
    name: "Enterprise",
    price: "Teklif Al",
    period: "",
    features: ["Sınırsız kullanıcı", "Tüm Pro özellikleri", "E-fatura (GİB)", "Özel entegrasyon", "SLA güvencesi"],
    cta: "İletişime Geç",
    highlight: false,
  },
];

const FAQS = [
  { q: "Demo hesap nasıl çalışır?", a: "Demo hesabına tek tıkla girip tüm modülleri ücretsiz deneyebilirsiniz. Veriler her gece sıfırlanır." },
  { q: "Gerçek hesap açmak ne kadar sürer?", a: "Formu doldurmanızın ardından ekibimiz 1 iş günü içinde şirketinizi sisteme kurar." },
  { q: "Verilerim güvende mi?", a: "Evet. HTTPS şifrelemesi, HttpOnly oturum token'ları ve izole multi-tenant veri mimarisi." },
  { q: "Mobil cihazdan kullanılabilir mi?", a: "Evet, tamamen responsive tasarım. iPhone/Android tarayıcılarında uygulama indirmeden çalışır." },
  { q: "E-fatura (GİB) desteği var mı?", a: "Pro ve Enterprise planlarda GİB entegrasyonu mevcuttur. Detay için bizimle iletişime geçin." },
];

export default function Home() {
  const [annual, setAnnual] = useState(false);

  return (
    <div className="min-h-screen bg-white text-slate-800 font-[var(--font-geist-sans)]">

      {/* NAV */}
      <nav className="fixed top-0 w-full z-50 bg-white/90 backdrop-blur border-b border-slate-100">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <span className="font-bold text-xl text-[#1a3a5c]">PrizmaDesk</span>
          <div className="hidden md:flex gap-6 text-sm text-slate-600">
            <a href="#ozellikler" className="hover:text-[#1e5f8c] transition-colors">Özellikler</a>
            <a href="#fiyatlandirma" className="hover:text-[#1e5f8c] transition-colors">Fiyatlandırma</a>
            <a href="#sss" className="hover:text-[#1e5f8c] transition-colors">SSS</a>
          </div>
          <div className="flex gap-2">
            <a href={`${APP_URL}/login`}
               className="px-4 py-2 text-sm text-slate-600 hover:text-slate-900 transition-colors">
              Giriş Yap
            </a>
            <a href={`${APP_URL}/demo`}
               className="px-4 py-2 text-sm bg-amber-400 hover:bg-amber-500 text-slate-900 font-semibold rounded-lg transition-colors">
              Ücretsiz Dene
            </a>
          </div>
        </div>
      </nav>

      {/* HERO */}
      <section className="pt-32 pb-24 px-4 bg-gradient-to-br from-[#1a3a5c] via-[#1e5f8c] to-[#1a4a70] text-white">
        <div className="max-w-4xl mx-auto text-center">
          <span className="inline-block px-3 py-1 text-xs font-semibold bg-white/15 rounded-full mb-6 tracking-wide uppercase">
            Türk KOBİ'leri için tasarlandı
          </span>
          <h1 className="text-4xl md:text-6xl font-bold leading-tight mb-6">
            Finans & İK'yı<br />
            <span className="text-amber-300">tek platformda</span> yönetin
          </h1>
          <p className="text-lg md:text-xl text-blue-100 max-w-2xl mx-auto mb-10">
            Fatura takibi, harcama bildirimleri, bordro, izin onayları ve raporlar —
            hepsi birbirine bağlı, her cihazdan erişilebilir.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <a href={`${APP_URL}/demo`}
               className="px-8 py-4 bg-amber-400 hover:bg-amber-500 text-slate-900 font-bold rounded-xl text-lg transition-colors shadow-lg">
              Ücretsiz Dene →
            </a>
            <a href="mailto:satis@prizmadesk.com"
               className="px-8 py-4 bg-white/10 hover:bg-white/20 text-white font-semibold rounded-xl text-lg transition-colors border border-white/20">
              Demo Talep Et
            </a>
          </div>
          <p className="mt-4 text-blue-200 text-sm">Kredi kartı gerekmez · 1 dakikada başlayın</p>
        </div>
      </section>

      {/* ÖZELLIKLER */}
      <section id="ozellikler" className="py-24 px-4 bg-slate-50">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">İhtiyacınız olan her şey</h2>
            <p className="text-slate-500 text-lg max-w-xl mx-auto">
              Onlarca ayrı araç yerine tek, entegre sistem.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => (
              <div key={f.title}
                   className="bg-white rounded-2xl p-6 border border-slate-100 hover:shadow-md hover:-translate-y-1 transition-all">
                <div className="text-3xl mb-4">{f.icon}</div>
                <h3 className="font-bold text-lg text-slate-900 mb-2">{f.title}</h3>
                <p className="text-slate-500 text-sm leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FİYATLANDIRMA */}
      <section id="fiyatlandirma" className="py-24 px-4">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl md:text-4xl font-bold text-slate-900 mb-4">Şeffaf fiyatlandırma</h2>
            <p className="text-slate-500 mb-6">Gizli ücret yok. İstediğiniz zaman iptal.</p>
            <div className="inline-flex items-center gap-3 bg-slate-100 p-1 rounded-xl">
              <button onClick={() => setAnnual(false)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${!annual ? "bg-white shadow text-slate-900" : "text-slate-500"}`}>
                Aylık
              </button>
              <button onClick={() => setAnnual(true)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${annual ? "bg-white shadow text-slate-900" : "text-slate-500"}`}>
                Yıllık <span className="text-emerald-600 font-semibold ml-1">%20 indirim</span>
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PRICING.map((p) => {
              const discounted = annual && p.price.startsWith("₺")
                ? `₺${Math.round(parseInt(p.price.replace(/\D/g, "")) * 0.8).toLocaleString("tr-TR")}`
                : p.price;
              return (
                <div key={p.name}
                     className={`rounded-2xl p-8 border-2 flex flex-col ${p.highlight ? "border-[#1e5f8c] bg-[#1a3a5c] text-white shadow-xl scale-105" : "border-slate-200 bg-white"}`}>
                  <div className={`text-xs font-bold uppercase tracking-widest mb-2 ${p.highlight ? "text-amber-300" : "text-slate-400"}`}>
                    {p.name}
                  </div>
                  <div className="mb-6">
                    <span className={`text-4xl font-bold ${p.highlight ? "text-white" : "text-slate-900"}`}>{discounted}</span>
                    <span className={`text-sm ml-1 ${p.highlight ? "text-blue-200" : "text-slate-400"}`}>{p.period}</span>
                  </div>
                  <ul className="space-y-3 mb-8 flex-1">
                    {p.features.map((f) => (
                      <li key={f} className="flex gap-2 text-sm">
                        <span className={p.highlight ? "text-amber-300" : "text-emerald-500"}>✓</span>
                        <span className={p.highlight ? "text-blue-100" : "text-slate-600"}>{f}</span>
                      </li>
                    ))}
                  </ul>
                  <a href={p.name === "Enterprise" ? "mailto:satis@prizmadesk.com" : `${APP_URL}/demo`}
                     className={`block text-center py-3 rounded-xl font-semibold transition-colors ${p.highlight ? "bg-amber-400 hover:bg-amber-500 text-slate-900" : "bg-slate-900 hover:bg-slate-700 text-white"}`}>
                    {p.cta}
                  </a>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* SSS */}
      <section id="sss" className="py-24 px-4 bg-slate-50">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl font-bold text-center text-slate-900 mb-12">Sık Sorulan Sorular</h2>
          <div className="space-y-3">
            {FAQS.map((f, i) => (
              <details key={i}
                       className="bg-white border border-slate-200 rounded-xl overflow-hidden group">
                <summary className="px-6 py-4 font-semibold text-slate-800 cursor-pointer list-none flex justify-between items-center hover:bg-slate-50">
                  {f.q}
                  <span className="text-slate-400 group-open:rotate-45 transition-transform text-xl leading-none">+</span>
                </summary>
                <p className="px-6 pb-4 text-slate-500 text-sm leading-relaxed">{f.a}</p>
              </details>
            ))}
          </div>
          <div className="text-center mt-8">
            <a href={`${APP_URL}/faq`} className="text-[#1e5f8c] font-semibold hover:underline text-sm">
              Tüm sorular →
            </a>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-4 bg-gradient-to-r from-[#1a3a5c] to-[#1e5f8c] text-white text-center">
        <div className="max-w-2xl mx-auto">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Hemen başlayın</h2>
          <p className="text-blue-100 mb-8 text-lg">Demo hesabını açın, 1 dakikada keşfedin.</p>
          <a href={`${APP_URL}/demo`}
             className="inline-block px-10 py-4 bg-amber-400 hover:bg-amber-500 text-slate-900 font-bold rounded-xl text-lg transition-colors shadow-lg">
            Ücretsiz Demo →
          </a>
          <p className="mt-4 text-blue-200 text-sm">
            Sorularınız için: <a href="mailto:satis@prizmadesk.com" className="underline">satis@prizmadesk.com</a>
          </p>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="bg-slate-900 text-slate-400 py-10 px-4 text-sm">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
          <span className="font-bold text-white text-base">PrizmaDesk</span>
          <div className="flex gap-6">
            <a href={`${APP_URL}/help`} className="hover:text-white transition-colors">Yardım</a>
            <a href={`${APP_URL}/faq`} className="hover:text-white transition-colors">SSS</a>
            <a href="mailto:destek@prizmadesk.com" className="hover:text-white transition-colors">Destek</a>
            <a href="mailto:satis@prizmadesk.com" className="hover:text-white transition-colors">Satış</a>
          </div>
          <span>© {new Date().getFullYear()} PrizmaDesk. Tüm hakları saklıdır.</span>
        </div>
      </footer>

    </div>
  );
}
