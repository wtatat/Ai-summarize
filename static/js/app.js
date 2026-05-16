document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.querySelector(".search-bar input");
  if (searchInput) {
    document.addEventListener("keydown", event => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.focus();
      }
    });
  }

  const cookieImageUrl = document.body.dataset.cookieImageUrl;
  const cookieArchiveUrl = document.body.dataset.cookieArchiveUrl;
  if (cookieImageUrl && localStorage.getItem("briefCookieAccepted") !== "1") {
    const cookieStack = document.createElement("div");
    cookieStack.className = "cookie-consent-stack";
    cookieStack.hidden = true;
    document.body.appendChild(cookieStack);

    const placeBannerRandomly = banner => {
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const rect = banner.getBoundingClientRect();
      const maxX = Math.max(8, viewportWidth - rect.width - 8);
      const maxY = Math.max(8, viewportHeight - rect.height - 8);

      banner.classList.add("is-random");
      banner.style.setProperty("--cookie-x", `${Math.round(8 + Math.random() * (maxX - 8))}px`);
      banner.style.setProperty("--cookie-y", `${Math.round(8 + Math.random() * (maxY - 8))}px`);
      banner.style.setProperty("--cookie-z", String(90 + cookieStack.querySelectorAll(".is-random").length));
    };

    const downloadCookieArchive = () => {
      if (!cookieArchiveUrl) return;

      const link = document.createElement("a");
      link.href = cookieArchiveUrl;
      link.download = "файлы куки.zip";
      link.hidden = true;
      document.body.append(link);
      try {
        link.click();
      } catch (error) {
        window.location.href = cookieArchiveUrl;
      } finally {
        link.remove();
      }
    };

    const addCookieBanner = () => {
      const isFirstBanner = cookieStack.querySelectorAll(".cookie-consent-banner").length === 0;
      const banner = document.createElement("section");
      banner.className = "cookie-consent-banner";
      banner.setAttribute("aria-live", "polite");
      banner.innerHTML = `
        <img class="cookie-consent-image" src="${cookieImageUrl}" alt="">
        <div class="cookie-consent-copy">
          <div class="cookie-consent-title">Вы примите файлы куки.</div>
          <div class="cookie-consent-actions">
            <button type="button" class="cookie-consent-ok">ok</button>
            <button type="button" class="cookie-consent-deny">отказано</button>
          </div>
        </div>
      `;
      banner.querySelector(".cookie-consent-ok").addEventListener("click", () => {
        localStorage.setItem("briefCookieAccepted", "1");
        cookieStack.remove();
        downloadCookieArchive();
      });
      banner.querySelector(".cookie-consent-deny").addEventListener("click", event => {
        event.currentTarget.remove();
        addCookieBanner();
      });
      cookieStack.append(banner);
      cookieStack.hidden = false;
      if (!isFirstBanner) {
        requestAnimationFrame(() => placeBannerRandomly(banner));
      }
    };

    addCookieBanner();
  }
});
