package it.mediaflow.atacroma

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import it.mediaflow.atacroma.ui.AtacRomaApp
import it.mediaflow.atacroma.ui.theme.AtacRomaTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AtacRomaTheme {
                AtacRomaApp()
            }
        }
    }
}
