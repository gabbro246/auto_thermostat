# Auto Thermostat

Auto Thermostat uses your Home Assistant sensors and switches to keep your rooms at the right temperature, automatically adjusting to who's home and offering a timed heating boost.

## What it does

Create separate thermostats for different rooms, all controlled through Home Assistant.

### Temperature sensors

Choose one or more temperature sensors. Auto Thermostat uses their average reading to control your heating.

### Home, Away and Sleep

Choose people or device trackers to automatically switch between Home and Away temperatures. You can also select Sleep for a different temperature at night, or adjust the temperature yourself.

### Boost

Start a timed heating boost, for example for 20 minutes, then return to your previous mode. You can also choose a compatible physical button: a short press starts Boost, and a long press stops it early.

### Dashboard cards

Auto Thermostat creates a regular Home Assistant climate entity, so you can use it with the built-in Thermostat card or compatible custom thermostat cards. No separate dashboard card is needed.

## Install with HACS

Make sure you have [HACS](https://hacs.xyz/) installed in Home Assistant.

1. Add the Auto Thermostat repository in **HACS → Custom repositories**, selecting **Integration** as the repository type.
2. In HACS, download **Auto Thermostat**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services**, choose **Add integration**, and search for **Auto Thermostat**.

## Set up a thermostat and add it to your dashboard

Give your thermostat a name, choose the switch that controls your heater and select your temperature sensors. You can also choose people for Home and Away detection and a button for Boost. Create multiple thermostats for different rooms if you want.

Once created, you can change the settings under **Settings → Devices & services → Auto Thermostat → Configure**.

To add a thermostat to your dashboard, enter edit mode, add a **Thermostat** card, and select your Auto Thermostat entity.

## Additional information

Auto Thermostat controls a switch or input boolean rather than another climate entity.

Found a bug or have a suggestion? Feel free to open an issue in the repository.

Licensed under the [MIT License](LICENSE).
