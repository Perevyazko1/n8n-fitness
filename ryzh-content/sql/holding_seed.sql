-- Контент-холдинг: стартовый список доноров (разведка 26.10.2026, утверждён владельцем)
-- и разовая чистка висящих черновиков. Применять после schema.sql:
--   docker compose exec -T db psql -U fitness -d fitness < ryzh-content/sql/holding_seed.sql
-- Идемпотентно: повторный прогон ничего не дублирует.
--
-- Замер на 26.10.2026: ER = медиана просмотров постов 2–21 дня ÷ подписчики.
-- Отсеяны личные лайфстайл-блоги (выстреливает личная жизнь, а не темы), врачи и БАДы
-- (тон «не эксперт»), крупные ПП-фермы (охват 1–3 % от подписчиков = мёртвая аудитория).

INSERT INTO content_sources (username, title, is_own, signal, note) VALUES
-- наш канал: только снапшоты для своих метрик
('ryzh_trener',           'Тренер Рыж',                          true,  true,  'свой канал'),
-- рецепты и бюджет
('nedorogo_i_vkysno',     'Бюджетные рецепты',                   false, true,  '5.1K, ER 34.8%; рецепты с ценой, постит редко'),
('dasha_budzget_recepti', 'Даша — бюджетно и вкусно',            false, true,  '4.3K, ER 18%, реакции 7.1% — лучшие в списке; закупки и меню с суммой'),
('sweetyzaika',           'ПП рецепты и похудение',              false, true,  '24K, ER 16.3%; белковая выпечка'),
('zerocaloriestg',        '0 калорий / ПП рецепты',              false, true,  '19K, ER 16.6%; ПП-десерты'),
('masha_pro_zozh',        'С любовью, ЗОЖ',                      false, true,  '10K, ER 14.8%'),
('zavtrakvsemugolova',    'Что на завтрак?',                     false, true,  '15K, ER 11.7%; лайфхаки'),
('o_zdorovei',            'Салатом в лицо',                      false, true,  '26K, ER 10.4%; живой тон'),
('happy_sweets_aliya',    'Алия: ППолезные рецепты',             false, true,  '12.6K, ER 9.3%'),
('nutri_channel',         'Nastuzzzi — нутрициолог без запретов', false, true, '29K, ER 5.5%'),
('breakfastblissdaily',   'Вкусный завтрак',                     false, false, '3.6K, ER 57% — подозрение на накрутку, только рецепты'),
('p_p_rezept',            'ПП-рецепты | Вкусная и полезная еда', false, false, '4.9K, ER 30% при 0 реакций — подозрение на накрутку'),
-- разборы продуктов и мифов
('zhzhgiss',              'ЖЖГИСЬ',                              false, true,  '135K, ER 27.3%; эталон «продукт под подозрением»'),
('TrenerBrin',            'Ярослав Брин',                        false, true,  '92.5K, ER 38.4%; постит редко'),
('bmchn',                 'BIOMACHINE',                          false, true,  '175K, ER 23.2%'),
('foodandscience',        'Food&Science',                        false, true,  '14.5K, ER 23%; постит редко'),
('calorie_weightloss',    'Калории и похудение',                 false, true,  '13.4K, ER 13.7%'),
('pro_appetit',           'pro_appetit | нутрициолог Ситнова',   false, true,  '16.8K, ER 14.8%'),
-- фитнес и похудение
('Max_anti_trainer',      'Метаморфоза',                         false, true,  '189K, ER 21.7%'),
('krylova_evgenia',       'Телега ЗОЖника',                      false, true,  '23K, ER 6.4%')
ON CONFLICT (username) DO NOTHING;

-- Редакторы: оба получают черновики в личку, любой может опубликовать / править.
INSERT INTO ryzh_editors (chat_id, name) VALUES
(648226895, 'владелец'),
(893232025, 'второй редактор')
ON CONFLICT (chat_id) DO NOTHING;

-- 11 черновиков 22.08–01.09 так и не разобраны; уводим их из 'draft', чтобы правка
-- текстом без reply не прилетела в старый пост («последний висящий черновик»).
UPDATE ryzh_posts SET status = 'stale'
WHERE status = 'draft' AND created_at < '2026-10-01';

-- Проверка
-- SELECT username, is_own, signal FROM content_sources ORDER BY is_own DESC, username;
-- SELECT status, count(*) FROM ryzh_posts GROUP BY 1;
-- SELECT * FROM ryzh_editors;

-- Направление с 31.10.2026: деньги и замены + рецепты с крючком. Разовая чистка.
-- Рецепты breakfastblissdaily остаются резервом копилки, новых с этих каналов не будет.
UPDATE ryzh_topics SET status = 'skipped'
WHERE status IN ('queued', 'proposed') AND rubric NOT IN ('price', 'swap', 'recipe')
  AND created_at < '2026-11-01';

UPDATE content_sources SET active = false WHERE NOT signal AND NOT is_own;

-- Посты про деньги за последние дни — на повторный разбор по новым правилам
-- (дубли темы отсекает Insert Topics по source_url).
UPDATE content_source_posts SET offered_at = NULL
WHERE posted_at > '2026-10-20'
  AND text ~* '[0-9] ?(₽|руб)|замен|вместо|дешевл|бюджетн|экономи';
