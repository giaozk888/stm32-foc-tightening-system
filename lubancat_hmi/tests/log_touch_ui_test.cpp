#define HMI_UI_TEST 1
#include "../src/main.cpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main(int argc, char **argv)
{
    qputenv("QT_QPA_PLATFORM", "offscreen");
    qputenv("LUBANCAT_HMI_LOG_PORT", "");
    QApplication app(argc, argv);
    HmiWindow window;
    window.activate(7);
    assert(window.importLogFile(QStringLiteral(LEVEL_FIXTURE)));
    window.show();
    app.processEvents();
    auto *table = window.findChild<QTableWidget *>(QStringLiteral("pigweedLogTable"));
    assert(table && table->rowCount() == 6);
    std::array<QPushButton *, 4> filters{};
    std::array<QPushButton *, 2> sources{};
    for (auto *button : window.findChildren<QPushButton *>()) {
        if (button->property("logFilterIndex").isValid())
            filters.at(button->property("logFilterIndex").toInt()) = button;
        if (button->property("logSourceIndex").isValid())
            sources.at(button->property("logSourceIndex").toInt()) = button;
    }
    const int rows[] = {6, 5, 4, 3};
    for (int i = 0; i < 4; ++i) {
        assert(filters[i] && filters[i]->height() >= 44);
        const auto position = filters[i]->mapTo(&window, QPoint(0, 0));
        assert(position.y() >= 0 && position.y() + filters[i]->height() <= window.height());
        filters[i]->click();
        assert(table->rowCount() == rows[i]);
        for (int j = 0; j < 4; ++j) assert(filters[j]->isChecked() == (i == j));
        filters[i]->click(); // Cannot de-select the active choice.
        assert(filters[i]->isChecked());
    }
    assert(window.findChildren<QComboBox *>().isEmpty());
    assert(sources[0] && sources[1]);
    sources[1]->click();
    assert(!sources[0]->isChecked() && sources[1]->isChecked());
    sources[0]->click();
    assert(sources[0]->isChecked() && !sources[1]->isChecked());
    assert(table->rowCount() == 3); // Source switch preserves existing records.
    filters[0]->click();
    assert(table->rowCount() == 6);
}
