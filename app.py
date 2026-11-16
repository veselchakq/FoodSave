import math
from datetime import date, timedelta
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="FoodSave", page_icon="🍽️", layout="wide")
DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)
ACTUAL = DATA / "actual_records.csv"
FORECASTS = DATA / "saved_forecasts.csv"

def read(path, cols):
    return pd.read_csv(path, parse_dates=["date"]) if path.exists() else pd.DataFrame(columns=cols)

def forecast_stats(h, target):
    same = h[h.date.dt.weekday == target.weekday()].sort_values("date").tail(8)
    sample = same if len(same) >= 2 else h.sort_values("date").tail(14)
    return (float(sample.sold.mean()), float(sample.sold.std(ddof=1)) if len(sample)>1 else 0.0, len(sample)) if len(sample) else (0,0,0)

demo = pd.read_csv(DATA/"sample_data.csv", parse_dates=["date"])
actual = read(ACTUAL, ["date","dish","sold","prepared","wasted","opening_stock","source"])
saved = read(FORECASTS, ["date","dish","forecast_sold","recommended_prepare"])
history = pd.concat([demo, actual], ignore_index=True).drop_duplicates(["date","dish"], keep="last")
history["date"] = pd.to_datetime(history.date)

with st.sidebar:
    st.title("🍽️ FoodSave")
    page = st.radio("Раздел", ["Главная","Загрузка данных","Прогнозирование","Внесение факта","Фактические результаты","Аналитика"])
st.title("🍽️ FoodSave")
st.caption("Система анализа продаж, прогнозирования спроса и учёта пищевых потерь")

if page == "Главная":
    st.header("Показатели")
    st.caption(f"Реальных записей: {len(actual)}. Демонстрационные данные искусственные.")
    a,b,c,d = st.columns(4)
    a.metric("Продано", int(history.sold.sum()))
    b.metric("Приготовлено", int(history.prepared.sum()))
    c.metric("Списано", int(history.wasted.sum()))
    d.metric("Доля списаний", f"{history.wasted.sum()/history.prepared.sum()*100:.1f}%" if history.prepared.sum() else "0%")
    daily = history.groupby("date",as_index=False).sold.sum()
    st.plotly_chart(px.line(daily,x="date",y="sold",markers=True),use_container_width=True)

elif page == "Загрузка данных":
    st.header("Импорт статистики")
    st.write("Обязательные поля: date, dish, sold, prepared, wasted.")
    f = st.file_uploader("CSV или Excel",type=["csv","xlsx","xls"])
    if f:
        try:
            raw = pd.read_csv(f) if f.name.endswith(".csv") else pd.read_excel(f)
            missing = [c for c in ["date","dish","sold","prepared","wasted"] if c not in raw.columns]
            if missing: st.error("Не хватает столбцов: "+", ".join(missing))
            else:
                raw["date"] = pd.to_datetime(raw.date,errors="coerce")
                for c in ["sold","prepared","wasted"]: raw[c] = pd.to_numeric(raw[c],errors="coerce")
                if raw[["date","sold","prepared","wasted"]].isna().any().any() or (raw[["sold","prepared","wasted"]]<0).any().any():
                    st.error("Проверь даты и неотрицательные числовые значения.")
                elif (raw.wasted>raw.prepared).any() or raw.duplicated(["date","dish"]).any():
                    st.error("Проверь списания и дубли дата+блюдо.")
                else:
                    st.dataframe(raw.head(30),use_container_width=True)
                    if st.button("Сохранить импорт",type="primary"):
                        raw["source"]="import"
                        merged=pd.concat([actual,raw],ignore_index=True).drop_duplicates(["date","dish"],keep="last")
                        merged.to_csv(ACTUAL,index=False,encoding="utf-8-sig")
                        st.success("Импорт сохранён в data/actual_records.csv. Перезапусти приложение.")
        except Exception as e: st.error(f"Ошибка файла: {e}")

elif page == "Прогнозирование":
    st.header("Прогноз спроса и рекомендации по приготовлению")
    latest = history.date.max().date()
    target = st.date_input("Дата планирования",value=max(date.today()+timedelta(days=1),latest+timedelta(days=1)))
    factor = st.slider("Коэффициент страхового резерва",0.0,1.5,0.5,0.1)
    dishes=sorted(history.dish.dropna().unique())
    st.subheader("Пригодные остатки")
    cols=st.columns(2); stocks={}
    for i,dish in enumerate(dishes):
        with cols[i%2]: stocks[dish]=st.number_input(f"{dish}, порций",min_value=0,step=1,key="v3_"+dish)
    rows=[]
    for dish in dishes:
        avg,std,n=forecast_stats(history[history.dish==dish],pd.Timestamp(target))
        demand=math.ceil(avg); reserve=math.ceil(std*factor); stock=stocks[dish]
        rows.append({"date":str(target),"Блюдо":dish,"Прогноз спроса":demand,"Резерв":reserve,
                     "Пригодный остаток":stock,"Рекомендуется приготовить":max(0,demand+reserve-stock),
                     "forecast_sold":demand,"recommended_prepare":max(0,demand+reserve-stock)})
    result=pd.DataFrame(rows)
    st.dataframe(result.drop(columns=["date","forecast_sold","recommended_prepare"]),use_container_width=True,hide_index=True)
    a,b=st.columns(2)
    a.metric("Прогноз продаж",int(result["Прогноз спроса"].sum()))
    b.metric("Рекомендуется приготовить",int(result["Рекомендуется приготовить"].sum()))
    st.download_button("Скачать рекомендации CSV",result.drop(columns=["forecast_sold","recommended_prepare"]).to_csv(index=False).encode("utf-8-sig"),"foodsave_plan.csv","text/csv")
    if st.button("Сохранить прогноз для проверки",type="primary"):
        new=result[["date","Блюдо","forecast_sold","recommended_prepare"]].rename(columns={"Блюдо":"dish"})
        merged=pd.concat([saved,new],ignore_index=True).drop_duplicates(["date","dish"],keep="last")
        merged.to_csv(FORECASTS,index=False,encoding="utf-8-sig")
        st.success("Прогноз сохранён. После внесения факта можно оценить точность.")
    st.warning("Базовая модель. Резерв предварительный; сроки годности, акции и ограничения кухни пока не учитываются.")

elif page == "Внесение факта":
    st.header("Внести результаты смены")
    st.write("Заполни форму после закрытия смены — отдельно для каждого блюда.")
    dishes=sorted(history.dish.dropna().unique())
    with st.form("fact_form",clear_on_submit=True):
        day=st.date_input("Дата смены",value=date.today())
        dish=st.selectbox("Блюдо",dishes)
        x1,x2,x3,x4=st.columns(4)
        opening=x1.number_input("Остаток на начало",min_value=0,step=1)
        prepared=x2.number_input("Приготовлено",min_value=0,step=1)
        sold=x3.number_input("Продано",min_value=0,step=1)
        wasted=x4.number_input("Списано",min_value=0,step=1)
        submit=st.form_submit_button("Сохранить факт",type="primary")
    if submit:
        if sold+wasted>opening+prepared:
            st.error("Продано + списано не может превышать остаток на начало + приготовлено.")
        elif opening+prepared+sold+wasted==0:
            st.error("Пустую запись сохранять нельзя.")
        else:
            new=pd.DataFrame([{"date":str(day),"dish":dish,"sold":sold,"prepared":prepared,
                               "wasted":wasted,"opening_stock":opening,"source":"manual"}])
            merged=pd.concat([actual,new],ignore_index=True).drop_duplicates(["date","dish"],keep="last")
            merged.to_csv(ACTUAL,index=False,encoding="utf-8-sig")
            st.success("Запись сохранена. Если дата и блюдо уже были, запись заменена.")
    if not actual.empty:
        st.subheader("Последние записи")
        st.dataframe(actual.sort_values("date",ascending=False).head(20),use_container_width=True)

elif page == "Фактические результаты":
    st.header("Фактические результаты")
    if actual.empty: st.info("Пока нет реальных записей. Добавь их в разделе «Внесение факта».")
    else:
        st.dataframe(actual.sort_values("date",ascending=False),use_container_width=True)
        st.download_button("Скачать фактические данные",actual.to_csv(index=False).encode("utf-8-sig"),"foodsave_actual.csv","text/csv")

else:
    st.header("Аналитика и отчётность")
    if actual.empty:
        st.info("Добавь реальные записи, чтобы получить фактическую аналитику.")
    else:
        a = actual.copy()
        a["date"] = pd.to_datetime(a["date"]).dt.date
        min_day, max_day = min(a.date), max(a.date)
        left, right = st.columns(2)
        start_day = left.date_input("Начало периода", value=min_day, key="report_start")
        end_day = right.date_input("Конец периода", value=max_day, key="report_end")
        if start_day > end_day:
            st.error("Дата начала не может быть позже даты окончания.")
            report = a.iloc[0:0].copy()
        else:
            report = a[(a.date >= start_day) & (a.date <= end_day)].copy()

        if report.empty:
            st.warning("За выбранный период фактических записей нет.")
        else:
            sold_total = int(report.sold.sum())
            prepared_total = int(report.prepared.sum())
            wasted_total = int(report.wasted.sum())
            waste_rate = wasted_total / prepared_total * 100 if prepared_total else 0
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Продано", f"{sold_total:,}".replace(",", " "))
            c2.metric("Приготовлено", f"{prepared_total:,}".replace(",", " "))
            c3.metric("Списано", f"{wasted_total:,}".replace(",", " "))
            c4.metric("Доля списаний", f"{waste_rate:.1f}%")

            by_dish = report.groupby("dish", as_index=False).agg(
                sold=("sold", "sum"), prepared=("prepared", "sum"), wasted=("wasted", "sum")
            )
            by_dish["Доля списаний, %"] = (
                by_dish.wasted / by_dish.prepared.replace(0, pd.NA) * 100
            ).fillna(0).round(1)
            st.subheader("Результаты по блюдам")
            st.dataframe(by_dish, use_container_width=True, hide_index=True)
            l, r = st.columns(2)
            l.plotly_chart(px.bar(by_dish, x="dish", y="wasted", title="Списания по блюдам"), use_container_width=True)
            r.plotly_chart(px.line(report.groupby("date", as_index=False).agg(
                sold=("sold", "sum"), wasted=("wasted", "sum")
            ), x="date", y=["sold", "wasted"], markers=True, title="Продажи и списания по дням"),
                use_container_width=True)

            st.download_button(
                "Скачать отчёт CSV",
                report.to_csv(index=False).encode("utf-8-sig"),
                "foodsave_period_report.csv",
                "text/csv",
            )

    st.subheader("Точность сохранённых прогнозов")
    if saved.empty or actual.empty:
        st.info("Сохрани прогноз заранее, а после даты прогноза внеси фактические продажи.")
    else:
        actual_for_check = actual.copy()
        actual_for_check["date"] = pd.to_datetime(actual_for_check["date"]).dt.strftime("%Y-%m-%d")
        saved_for_check = saved.copy()
        saved_for_check["date"] = pd.to_datetime(saved_for_check["date"]).dt.strftime("%Y-%m-%d")
        joined = saved_for_check.merge(
            actual_for_check[["date", "dish", "sold"]], on=["date", "dish"], how="inner"
        )
        if joined.empty:
            st.info("Нет совпадений по дате и блюду. Сначала сохрани прогноз на дату, затем внеси факт за эту дату.")
        else:
            joined["absolute_error"] = (joined.forecast_sold - joined.sold).abs()
            joined["signed_error"] = joined.forecast_sold - joined.sold
            mae = joined.absolute_error.mean()
            wape = joined.absolute_error.sum() / joined.sold.sum() * 100 if joined.sold.sum() else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Сопоставлено прогнозов", len(joined))
            c2.metric("MAE", f"{mae:.2f} порции")
            c3.metric("WAPE", f"{wape:.1f}%")
            st.caption("MAE — средняя абсолютная ошибка в порциях. WAPE — суммарная абсолютная ошибка относительно фактических продаж. Меньше — лучше.")
            st.dataframe(
                joined[["date", "dish", "forecast_sold", "sold", "signed_error", "absolute_error"]],
                use_container_width=True, hide_index=True
            )
            st.download_button(
                "Скачать отчёт точности прогнозов",
                joined.to_csv(index=False).encode("utf-8-sig"),
                "foodsave_forecast_accuracy.csv",
                "text/csv",
            )

st.divider()
st.caption("Демонстрационная история искусственная. Реальные показатели рассчитываются только по внесённым данным.")
