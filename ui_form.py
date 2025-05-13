# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'altform.ui'
##
## Created by: Qt User Interface Compiler version 6.9.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QHeaderView,
    QMainWindow, QMenu, QMenuBar, QScrollArea,
    QSizePolicy, QSplitter, QStatusBar, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1137, 580)
        self.actionOpen_Workspace = QAction(MainWindow)
        self.actionOpen_Workspace.setObjectName(u"actionOpen_Workspace")
        self.actionSettings = QAction(MainWindow)
        self.actionSettings.setObjectName(u"actionSettings")
        self.actionToggle_Theme = QAction(MainWindow)
        self.actionToggle_Theme.setObjectName(u"actionToggle_Theme")
        self.actionFlip_ECG = QAction(MainWindow)
        self.actionFlip_ECG.setObjectName(u"actionFlip_ECG")
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.Splitter = QSplitter(self.centralwidget)
        self.Splitter.setObjectName(u"Splitter")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(1)
        sizePolicy.setHeightForWidth(self.Splitter.sizePolicy().hasHeightForWidth())
        self.Splitter.setSizePolicy(sizePolicy)
        self.Splitter.setBaseSize(QSize(0, 0))
        self.Splitter.setFrameShape(QFrame.Shape.NoFrame)
        self.Splitter.setLineWidth(0)
        self.Splitter.setOrientation(Qt.Orientation.Horizontal)
        self.Treeframe = QFrame(self.Splitter)
        self.Treeframe.setObjectName(u"Treeframe")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.Treeframe.sizePolicy().hasHeightForWidth())
        self.Treeframe.setSizePolicy(sizePolicy1)
        self.Treeframe.setBaseSize(QSize(0, 0))
        self.Treeframe.setStyleSheet(u"")
        self.Treeframe.setFrameShape(QFrame.Shape.StyledPanel)
        self.Treeframe.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout = QHBoxLayout(self.Treeframe)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.treeWidget = QTreeWidget(self.Treeframe)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, u"1");
        self.treeWidget.setHeaderItem(__qtreewidgetitem)
        self.treeWidget.setObjectName(u"treeWidget")
        self.treeWidget.setEnabled(True)
        self.treeWidget.setRootIsDecorated(True)
        self.treeWidget.setAnimated(True)

        self.horizontalLayout.addWidget(self.treeWidget)

        self.Splitter.addWidget(self.Treeframe)
        self.Views = QTabWidget(self.Splitter)
        self.Views.setObjectName(u"Views")
        self.Views.setStyleSheet(u"border: 1px solid gray;\n"
"border-radius: 1px;\n"
"")
        self.Views.setTabPosition(QTabWidget.TabPosition.North)
        self.Views.setTabShape(QTabWidget.TabShape.Triangular)
        self.Views.setIconSize(QSize(32, 32))
        self.Views.setDocumentMode(True)
        self.PreProcessing = QWidget()
        self.PreProcessing.setObjectName(u"PreProcessing")
        sizePolicy1.setHeightForWidth(self.PreProcessing.sizePolicy().hasHeightForWidth())
        self.PreProcessing.setSizePolicy(sizePolicy1)
        self.horizontalLayout_2 = QHBoxLayout(self.PreProcessing)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.mplPreProcessing = QWidget(self.PreProcessing)
        self.mplPreProcessing.setObjectName(u"mplPreProcessing")
        sizePolicy1.setHeightForWidth(self.mplPreProcessing.sizePolicy().hasHeightForWidth())
        self.mplPreProcessing.setSizePolicy(sizePolicy1)

        self.horizontalLayout_2.addWidget(self.mplPreProcessing)

        self.Views.addTab(self.PreProcessing, "")
        self.Series = QWidget()
        self.Series.setObjectName(u"Series")
        sizePolicy1.setHeightForWidth(self.Series.sizePolicy().hasHeightForWidth())
        self.Series.setSizePolicy(sizePolicy1)
        self.horizontalLayout_7 = QHBoxLayout(self.Series)
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.mplIBISeries = QWidget(self.Series)
        self.mplIBISeries.setObjectName(u"mplIBISeries")
        sizePolicy1.setHeightForWidth(self.mplIBISeries.sizePolicy().hasHeightForWidth())
        self.mplIBISeries.setSizePolicy(sizePolicy1)

        self.horizontalLayout_7.addWidget(self.mplIBISeries)

        self.Views.addTab(self.Series, "")
        self.Poincare = QWidget()
        self.Poincare.setObjectName(u"Poincare")
        sizePolicy1.setHeightForWidth(self.Poincare.sizePolicy().hasHeightForWidth())
        self.Poincare.setSizePolicy(sizePolicy1)
        self.horizontalLayout_3 = QHBoxLayout(self.Poincare)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.mplPoincare = QWidget(self.Poincare)
        self.mplPoincare.setObjectName(u"mplPoincare")
        sizePolicy1.setHeightForWidth(self.mplPoincare.sizePolicy().hasHeightForWidth())
        self.mplPoincare.setSizePolicy(sizePolicy1)

        self.horizontalLayout_3.addWidget(self.mplPoincare)

        self.Views.addTab(self.Poincare, "")
        self.Epochs = QWidget()
        self.Epochs.setObjectName(u"Epochs")
        sizePolicy1.setHeightForWidth(self.Epochs.sizePolicy().hasHeightForWidth())
        self.Epochs.setSizePolicy(sizePolicy1)
        self.horizontalLayout_4 = QHBoxLayout(self.Epochs)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.mplEpochs = QWidget(self.Epochs)
        self.mplEpochs.setObjectName(u"mplEpochs")
        sizePolicy1.setHeightForWidth(self.mplEpochs.sizePolicy().hasHeightForWidth())
        self.mplEpochs.setSizePolicy(sizePolicy1)

        self.horizontalLayout_4.addWidget(self.mplEpochs)

        self.Views.addTab(self.Epochs, "")
        self.PSD = QWidget()
        self.PSD.setObjectName(u"PSD")
        sizePolicy1.setHeightForWidth(self.PSD.sizePolicy().hasHeightForWidth())
        self.PSD.setSizePolicy(sizePolicy1)
        self.horizontalLayout_5 = QHBoxLayout(self.PSD)
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.mplPSD = QWidget(self.PSD)
        self.mplPSD.setObjectName(u"mplPSD")
        sizePolicy1.setHeightForWidth(self.mplPSD.sizePolicy().hasHeightForWidth())
        self.mplPSD.setSizePolicy(sizePolicy1)
        self.verticalLayout_2 = QVBoxLayout(self.mplPSD)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.scrollArea = QScrollArea(self.mplPSD)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 98, 28))
        sizePolicy1.setHeightForWidth(self.scrollAreaWidgetContents.sizePolicy().hasHeightForWidth())
        self.scrollAreaWidgetContents.setSizePolicy(sizePolicy1)
        self.scrollArea.setWidget(self.scrollAreaWidgetContents)

        self.verticalLayout_2.addWidget(self.scrollArea)


        self.horizontalLayout_5.addWidget(self.mplPSD)

        self.Views.addTab(self.PSD, "")
        self.Parameters = QWidget()
        self.Parameters.setObjectName(u"Parameters")
        sizePolicy1.setHeightForWidth(self.Parameters.sizePolicy().hasHeightForWidth())
        self.Parameters.setSizePolicy(sizePolicy1)
        self.horizontalLayout_6 = QHBoxLayout(self.Parameters)
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.mplParameters = QWidget(self.Parameters)
        self.mplParameters.setObjectName(u"mplParameters")
        sizePolicy1.setHeightForWidth(self.mplParameters.sizePolicy().hasHeightForWidth())
        self.mplParameters.setSizePolicy(sizePolicy1)

        self.horizontalLayout_6.addWidget(self.mplParameters)

        self.Views.addTab(self.Parameters, "")
        self.Splitter.addWidget(self.Views)

        self.verticalLayout.addWidget(self.Splitter)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1137, 22))
        self.menufile = QMenu(self.menubar)
        self.menufile.setObjectName(u"menufile")
        self.menuView = QMenu(self.menubar)
        self.menuView.setObjectName(u"menuView")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menufile.menuAction())
        self.menubar.addAction(self.menuView.menuAction())
        self.menufile.addAction(self.actionOpen_Workspace)
        self.menufile.addSeparator()
        self.menufile.addAction(self.actionFlip_ECG)
        self.menuView.addAction(self.actionSettings)

        self.retranslateUi(MainWindow)

        self.Views.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.actionOpen_Workspace.setText(QCoreApplication.translate("MainWindow", u"Open Workspace", None))
        self.actionSettings.setText(QCoreApplication.translate("MainWindow", u"Settings", None))
        self.actionToggle_Theme.setText(QCoreApplication.translate("MainWindow", u"Toggle Theme", None))
        self.actionFlip_ECG.setText(QCoreApplication.translate("MainWindow", u"Flip ECG", None))
        self.Views.setTabText(self.Views.indexOf(self.PreProcessing), QCoreApplication.translate("MainWindow", u"Preprocessing", None))
        self.Views.setTabText(self.Views.indexOf(self.Series), QCoreApplication.translate("MainWindow", u"IBI Series", None))
        self.Views.setTabText(self.Views.indexOf(self.Poincare), QCoreApplication.translate("MainWindow", u"Poincare", None))
        self.Views.setTabText(self.Views.indexOf(self.Epochs), QCoreApplication.translate("MainWindow", u"Epochs", None))
        self.Views.setTabText(self.Views.indexOf(self.PSD), QCoreApplication.translate("MainWindow", u"PSD", None))
        self.Views.setTabText(self.Views.indexOf(self.Parameters), QCoreApplication.translate("MainWindow", u"Parameters", None))
        self.menufile.setTitle(QCoreApplication.translate("MainWindow", u"WorkSpace", None))
        self.menuView.setTitle(QCoreApplication.translate("MainWindow", u"View", None))
    # retranslateUi

