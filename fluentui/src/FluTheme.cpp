#include "FluTheme.h"

#include "Def.h"
#include <QPalette>
#include "FluApp.h"
#include <QGuiApplication>

FluTheme::FluTheme(QObject *parent)
    : QObject{parent}
{
    connect(this,&FluTheme::darkModeChanged,this,[=]{
        Q_EMIT darkChanged();
    });
    primaryColor(FluApp::fluColors->Blue());
    nativeText(false);
    frameless(true);
    darkMode(Fluent_DarkMode::Fluent_DarkModeType::Light);
    qApp->installEventFilter(this);
}

bool FluTheme::eventFilter(QObject *obj, QEvent *event)
{
    Q_UNUSED(obj);
    if (event->type() == QEvent::ApplicationPaletteChange)
    {
        // 只通知 QML 刷新，不要把事件吞掉，否则其它控件收不到应用级调色板变化
        Q_EMIT darkChanged();
    }
    return false;
}

bool FluTheme::systemDark()
{
    QPalette palette = qApp->palette();
    QColor color = palette.color(QPalette::Window).rgb();
    return !(color.red() * 0.2126 + color.green() * 0.7152 + color.blue() * 0.0722 > 255 / 2);
}

bool FluTheme::dark(){
    if(_darkMode == Fluent_DarkMode::Fluent_DarkModeType::Dark){
        return true;
    }else if(_darkMode == Fluent_DarkMode::Fluent_DarkModeType::Light){
        return false;
    }else if(_darkMode == Fluent_DarkMode::Fluent_DarkModeType::System){
        return systemDark();
    }else{
        return false;
    }
}
