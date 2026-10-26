# WORKLOG — инфраструктура

Сервер, nginx, TLS, общий n8n. Заметки по конкретным автоматизациям — в `WORKLOG.md` их папок
(см. таблицу проектов в `CLAUDE.md`).

- [Safe Browsing: «Опасный сайт» на n8n-fitness.ru](#safe-browsing-опасный-сайт-на-n8n-fitnessru) — UI n8n закрыт паролем, запрос в Google, 26.10.2026

---

## Safe Browsing: «Опасный сайт» на n8n-fitness.ru

Состояние на **26.10.2026**. Chrome показывал красную страницу «Опасный сайт» на n8n-fitness.ru.
В Search Console → «Проблемы безопасности»: «Обманные страницы», URL с проблемами — «Отсутствует».

---

### 1. Причина

Взлома нет. Проверено: nginx проксирует только в n8n (:5678) и Django (:8001), чужих location
и внедрённых скриптов нет, контейнеры без рестартов, в логах только фон сканеров
(`/.git/config`, `/.env`, `/wp-login.php`).

Ложное срабатывание: краулер Google видел на `/` форму логина n8n с брендом
«n8n.io - Workflow Automation» на чужом домене (да ещё с «n8n» в имени) — для автоматики это
копия чужой страницы входа, то есть фишинг. Django `/admin` — ещё одна открытая форма логина.

---

### 2. Что сделано

- **nginx** (`/root/nginx/nginx.conf` на сервере, копия — `nginx-n8n.conf` в репо): весь vhost
  за `satisfy any` + basic auth, без пароля — с VPN amnezia-wg (`172.17.0.3`).
  Публичны только `/webhook/`, `/webhook-test/`, `/webhook-waiting/`, `/api/`,
  `/django-static/`, `/healthz` и `robots.txt` (`Disallow: /`).
- **htpasswd** — `/etc/letsencrypt/n8n-fitness.htpasswd`, логин `andrey`. Лежит там, потому что
  это единственный каталог хоста, смонтированный в nginx-контейнер (его compose не наш).
  Пароль в репо и ворклог не пишу.
- **Бэкап** старого конфига: `/root/nginx/nginx.conf.bak-2026-10-26`.
  Откат: `cat` бэкапа в `nginx.conf` → `docker exec nginx nginx -t && docker exec nginx nginx -s reload`.
- Проверено после применения: без пароля `/`, `/rest`, `/admin` → 401; с паролем → 200;
  вебхуки проходят (ассистент на визитке и Telegram-бот ответили). `/api/` отдаёт 401
  `missing initData` — это сам Django на запрос не из Mini App, не nginx.
- Исправлен устаревший путь к конфигу nginx в `CLAUDE.md` и `README.md`
  (`/root/vacuum_remote/...` → `/root/nginx/nginx.conf`), в `CLAUDE.md` — раздел «Доступ к UI».
- Коммит `56b6a8d`, запушен.
- В Search Console отправлен запрос на проверку.

---

### 3. Что дальше

1. Ждать ответ Google (обычно 1–3 дня) — почта и Search Console → «Проблемы безопасности».
2. Если откажут — разобрать их ответ. Запасной вариант: увести UI n8n на поддомен/домен
   без «n8n» в имени.
3. Не открывать UI n8n и Django `/admin` наружу при будущих правках nginx — иначе пометка вернётся.
