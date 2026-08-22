# Chaquopy needs its runtime classes and the Java classes Python reflects on.
-keep class com.chaquo.python.** { *; }
-keep class com.expstudio.pycmd.python.** { *; }
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
