from copy import copy

from cereal import car
from opendbc.can.parser import CANParser
from opendbc.can.can_define import CANDefine
from selfdrive.config import Conversions as CV
from selfdrive.car.interfaces import CarStateBase
from selfdrive.car.chrysler.values import DBC, STEER_THRESHOLD


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    can_define = CANDefine(DBC[CP.carFingerprint]['pt'])
    self.shifter_values = can_define.dv["GEAR"]['PRNDL']

  def update(self, cp, cp_cam):

    ret = car.CarState.new_message()

    self.frame = int(cp.vl["EPS_STATUS"]['COUNTER'])

    ret.doorOpen = any([cp.vl["DOORS"]['DOOR_OPEN_FL'],
                        cp.vl["DOORS"]['DOOR_OPEN_FR'],
                        cp.vl["DOORS"]['DOOR_OPEN_RL'],
                        cp.vl["DOORS"]['DOOR_OPEN_RR']])
    ret.seatbeltUnlatched = cp.vl["SEATBELT_STATUS"]['SEATBELT_DRIVER_UNLATCHED'] == 1

    ret.brakePressed = cp.vl["BRAKE_2"]['BRAKE_PEDAL'] == 1  # driver-only
    ret.brake = cp.vl["BRAKE_1"]['BRAKE_VAL_TOTAL']
    ret.brakeLights = bool(cp.vl["BRAKE_2"]['BRAKE_LIGHT'])
    ret.gas = cp.vl["ACCEL_GAS_22F"]['GAS_PEDAL_POS']
    ret.gasPressed = ret.gas > 1e-5

    ret.espDisabled = (cp.vl["TRACTION_BUTTON"]['TRACTION_OFF'] == 1)

    ret.wheelSpeeds.fl = cp.vl['WHEEL_SPEEDS']['WHEEL_SPEED_FL']
    ret.wheelSpeeds.rr = cp.vl['WHEEL_SPEEDS']['WHEEL_SPEED_RR']
    ret.wheelSpeeds.rl = cp.vl['WHEEL_SPEEDS']['WHEEL_SPEED_RL']
    ret.wheelSpeeds.fr = cp.vl['WHEEL_SPEEDS']['WHEEL_SPEED_FR']
    ret.vEgoRaw = cp.vl['BRAKE_1']['VEHICLE_SPEED_KPH'] * CV.KPH_TO_MS
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.standstill = bool(cp.vl['BRAKE_1']['STANDSTILL'])

    ret.leftBlinker = cp.vl["STEERING_LEVERS"]['TURN_SIGNALS'] == 1
    ret.rightBlinker = cp.vl["STEERING_LEVERS"]['TURN_SIGNALS'] == 2
    ret.steeringAngleDeg = cp.vl["STEERING"]['STEER_ANGLE']
    ret.steeringRateDeg = cp.vl["STEERING"]['STEERING_RATE']
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(cp.vl['GEAR']['PRNDL'], None))

    ret.cruiseState.enabled = bool(cp.vl["ACC_2"]['ACC_ENABLED'])  # ACC is green.
    ret.cruiseState.available = bool(cp.vl["ACC_2"]['ACC_AVAILABLE'])
    ret.cruiseState.speed = cp.vl["DASHBOARD"]['ACC_SPEED_CONFIG_KPH'] * CV.KPH_TO_MS
    # CRUISE_STATE is a three bit msg, 0 is off, 1 and 2 are Non-ACC mode, 3 and 4 are ACC mode, find if there are other states too
    ret.cruiseState.nonAdaptive = cp.vl["DASHBOARD"]['CRUISE_STATE'] in [1, 2]

    ret.steeringTorque = cp.vl["EPS_STATUS"]["TORQUE_DRIVER"]
    ret.steeringTorqueEps = cp.vl["EPS_STATUS"]["TORQUE_MOTOR"]
    ret.steeringPressed = abs(ret.steeringTorque) > STEER_THRESHOLD
    self.steerError = cp.vl["EPS_STATUS"]["LKAS_STEER_FAULT"] == 4
    self.apaFault = cp.vl["EPS_STATUS"]["APA_STEER_FAULT"] == 1
    self.apasteerOn = cp.vl["EPS_STATUS"]["APA_ACTIVE"] == 1

    ret.genericToggle = bool(cp.vl["STEERING_LEVERS"]['HIGH_BEAM_FLASH'])

    ret.leftBlindspot = 7 > cp.vl["BLIND_SPOT_WARNINGS"]['BLIND_SPOT_LEFT'] > 0
    ret.rightBlindspot = 7 > cp.vl["BLIND_SPOT_WARNINGS"]['BLIND_SPOT_RIGHT'] > 0

    self.lkas_counter = cp_cam.vl["LKAS_COMMAND"]['COUNTER']
    self.lkas_status_ok = cp_cam.vl["LKAS_HEARTBIT"]['LKAS_BUTTON_LED']
    self.apa_steer_status = cp.vl["AUTO_PARK_REQUEST"]['APA_ACTIVE'] == 1
    self.veh_on = cp.vl["HYBRID_ECU"]['VEH_ON'] == 1
    self.acc_hold = bool(cp.vl["ACC_2"]['ACC_STOP'])
    self.lead_dist = cp.vl["DASHBOARD"]['LEAD_DIST']
    self.wheel_button_counter = cp.vl["WHEEL_BUTTONS"]['COUNTER']

    self.acc_button_pressed = bool(cp.vl["WHEEL_BUTTONS"]['ACC_CANCEL']) \
                              or bool(cp.vl["WHEEL_BUTTONS"]['ACC_RESUME']) \
                              or bool(cp.vl["WHEEL_BUTTONS"]['ACC_SPEED_INC']) \
                              or bool(cp.vl["WHEEL_BUTTONS"]['ACC_SPEED_DEC']) \
                              or bool(cp.vl["WHEEL_BUTTONS"]['ACC_FOLLOW_DEC']) \
                              or bool(cp.vl["WHEEL_BUTTONS"]['ACC_FOLLOW_INC'])
    return ret

  @staticmethod
  def get_can_parser(CP):
    signals = [
      # sig_name, sig_address, default
      ("PRNDL", "GEAR", 0),
      ("DOOR_OPEN_FL", "DOORS", 0),
      ("DOOR_OPEN_FR", "DOORS", 0),
      ("DOOR_OPEN_RL", "DOORS", 0),
      ("DOOR_OPEN_RR", "DOORS", 0),
      ("BRAKE_PEDAL", "BRAKE_2", 0),
      ("GAS_PEDAL_POS", "ACCEL_GAS_22F", 0),
      ("WHEEL_SPEED_FL", "WHEEL_SPEEDS", 0),
      ("WHEEL_SPEED_RR", "WHEEL_SPEEDS", 0),
      ("WHEEL_SPEED_RL", "WHEEL_SPEEDS", 0),
      ("WHEEL_SPEED_FR", "WHEEL_SPEEDS", 0),
      ("STEER_ANGLE", "STEERING", 0),
      ("STEERING_RATE", "STEERING", 0),
      ("TURN_SIGNALS", "STEERING_LEVERS", 0),
      ("ACC_ENABLED", "ACC_2", 0),
      ("ACC_AVAILABLE", "ACC_2", 0),
      ("HIGH_BEAM_FLASH", "STEERING_LEVERS", 0),
      ("ACC_SPEED_CONFIG_KPH", "DASHBOARD", 0),
      ("LEAD_DIST", "DASHBOARD", 0),
      ("CRUISE_STATE", "DASHBOARD", 0),
      ("TORQUE_DRIVER", "EPS_STATUS", 0),
      ("DRIVER_TAKEOVER", "EPS_STATUS", 0),
      ("TORQUE_MOTOR", "EPS_STATUS", 0),
      ("LKAS_STEER_FAULT", "EPS_STATUS", 0),
      ("COUNTER", "EPS_STATUS", -1),
      ("TRACTION_OFF", "TRACTION_BUTTON", 0),
      ("SEATBELT_DRIVER_UNLATCHED", "SEATBELT_STATUS", 0),
      ("APA_ACTIVE", "EPS_STATUS", 0),
      ("APA_STEER_FAULT", "EPS_STATUS", 0),
      ("VEH_ON", "HYBRID_ECU", 0),
      ("ACC_STOP", "ACC_2", 0),
      ("BLIND_SPOT_RIGHT", "BLIND_SPOT_WARNINGS", 0),
      ("BLIND_SPOT_LEFT", "BLIND_SPOT_WARNINGS", 0),
      ("COUNTER", "WHEEL_BUTTONS", 0),
      ("ACC_RESUME", "WHEEL_BUTTONS", 0),
      ("ACC_CANCEL", "WHEEL_BUTTONS", 0),
      ("ACC_SPEED_INC", "WHEEL_BUTTONS", 0),
      ("ACC_SPEED_DEC", "WHEEL_BUTTONS", 0),
      ("ACC_FOLLOW_INC", "WHEEL_BUTTONS", 0),
      ("ACC_FOLLOW_DEC", "WHEEL_BUTTONS", 0),
      ("ACC_DISTANCE_CONFIG_2", "DASHBOARD", 0),
      ("STANDSTILL", "BRAKE_1", 0),
      ("BRAKE_VAL_TOTAL", "BRAKE_1", 0),
      ("VEHICLE_SPEED_KPH", "BRAKE_1", 0),
      ("BRAKE_LIGHT", "BRAKE_2", 0),
    ]

    checks = [
      # sig_address, frequency
      ("BRAKE_2", 50),
      ("EPS_STATUS", 100),
      ("SPEED_1", 100),
      ("WHEEL_SPEEDS", 50),
      ("STEERING", 100),
      ("ACC_2", 50),
      ("GEAR", 50),
      ("ACCEL_GAS_134", 50),
      ("DASHBOARD", 15),
      ("STEERING_LEVERS", 10),
      ("SEATBELT_STATUS", 2),
      ("DOORS", 1),
      ("TRACTION_BUTTON", 1),
      ("BLIND_SPOT_WARNINGS", 2),
      ("BRAKE_1", 50),
    ]

    return CANParser(DBC[CP.carFingerprint]['pt'], signals, checks, 0)

  @staticmethod
  def get_cam_can_parser(CP):
    signals = [
      # sig_name, sig_address, default
      ("COUNTER", "LKAS_COMMAND", -1),
      ("LKAS_BUTTON_LED", "LKAS_HEARTBIT", -1)
    ]
    checks = [
      ("LKAS_COMMAND", 100),
      ("LKAS_HEARTBIT", 10),
      ("LKAS_HUD", 4),
    ]

    return CANParser(DBC[CP.carFingerprint]['pt'], signals, checks, 2)
